import json
import os

import numpy as np
import requests
import tensorflow as tf
import transformers
from absl import app
from absl import flags

import keras_hub
from tools.checkpoint_conversion.checkpoint_conversion_utils import (
    get_md5_checksum,
)

PRESET_MAP = {
    "distil_bert_base_en_uncased": "distilbert-base-uncased",
    "distil_bert_base_en_cased": "distilbert-base-cased",
    "distil_bert_base_multi_cased": "distilbert-base-multilingual-cased",
}

EXTRACT_DIR = "./{}"

FLAGS = flags.FLAGS
flags.DEFINE_string(
    "preset", None, f"Must be one of {','.join(PRESET_MAP.keys())}"
)


def download_files(hf_model_name):
    print("-> Download original vocab and config.")

    extract_dir = EXTRACT_DIR.format(FLAGS.preset)
    if not os.path.exists(extract_dir):
        os.makedirs(extract_dir)

    # Config.
    config_path = os.path.join(extract_dir, "config.json")
    response = requests.get(
        f"https://huggingface.co/{hf_model_name}/raw/main/config.json"
    )
    open(config_path, "wb").write(response.content)
    print(f"`{config_path}`")

    # Vocab.
    vocab_path = os.path.join(extract_dir, "vocab.txt")
    response = requests.get(
        f"https://huggingface.co/{hf_model_name}/raw/main/vocab.txt"
    )
    open(vocab_path, "wb").write(response.content)
    print(f"`{vocab_path}`")


def define_preprocessor(hf_model_name):
    print("\n-> Define the tokenizers.")
    extract_dir = EXTRACT_DIR.format(FLAGS.preset)
    vocab_path = os.path.join(extract_dir, "vocab.txt")

    keras_hub_tokenizer = keras_hub.models.DistilBertTokenizer(
        vocabulary=vocab_path,
    )
    keras_hub_preprocessor = (
        keras_hub.models.DistilBertTextClassifierPreprocessor(
            keras_hub_tokenizer
        )
    )

    hf_tokenizer = transformers.AutoTokenizer.from_pretrained(hf_model_name)

    print("\n-> Print MD5 checksum of the vocab files.")
    print(f"`{vocab_path}` md5sum: ", get_md5_checksum(vocab_path))

    return keras_hub_preprocessor, hf_tokenizer


def convert_checkpoints(keras_hub_model, hf_model):
    print("\n-> Convert original weights to KerasHub format.")

    extract_dir = EXTRACT_DIR.format(FLAGS.preset)
    config_path = os.path.join(extract_dir, "config.json")

    # Build config.
    cfg = {}
    with open(config_path, "r") as pt_cfg_handler:
        pt_cfg = json.load(pt_cfg_handler)
    cfg["vocabulary_size"] = pt_cfg["vocab_size"]
    cfg["num_layers"] = pt_cfg["n_layers"]
    cfg["num_heads"] = pt_cfg["n_heads"]
    cfg["hidden_dim"] = pt_cfg["dim"]
    cfg["intermediate_dim"] = pt_cfg["hidden_dim"]
    cfg["dropout"] = pt_cfg["dropout"]
    cfg["max_sequence_length"] = pt_cfg["max_position_embeddings"]

    print("Config:", cfg)

    hf_wts = hf_model.state_dict()
    print("Original weights:")
    print(
        str(hf_wts.keys())
        .replace(", ", "\n")
        .replace("odict_keys([", "")
        .replace("]", "")
        .replace(")", "")
    )

    keras_hub_model.get_layer(
        "token_and_position_embedding"
    ).token_embedding.embeddings.assign(
        hf_wts["embeddings.word_embeddings.weight"]
    )
    keras_hub_model.get_layer(
        "token_and_position_embedding"
    ).position_embedding.position_embeddings.assign(
        hf_wts["embeddings.position_embeddings.weight"]
    )

    keras_hub_model.get_layer("embeddings_layer_norm").gamma.assign(
        hf_wts["embeddings.LayerNorm.weight"]
    )
    keras_hub_model.get_layer("embeddings_layer_norm").beta.assign(
        hf_wts["embeddings.LayerNorm.bias"]
    )

    for i in range(keras_hub_model.num_layers):
        keras_hub_model.get_layer(
            f"transformer_layer_{i}"
        )._self_attention_layer._query_dense.kernel.assign(
            hf_wts[f"transformer.layer.{i}.attention.q_lin.weight"]
            .transpose(1, 0)
            .reshape((cfg["hidden_dim"], cfg["num_heads"], -1))
            .numpy()
        )
        keras_hub_model.get_layer(
            f"transformer_layer_{i}"
        )._self_attention_layer._query_dense.bias.assign(
            hf_wts[f"transformer.layer.{i}.attention.q_lin.bias"]
            .reshape((cfg["num_heads"], -1))
            .numpy()
        )

        keras_hub_model.get_layer(
            f"transformer_layer_{i}"
        )._self_attention_layer._key_dense.kernel.assign(
            hf_wts[f"transformer.layer.{i}.attention.k_lin.weight"]
            .transpose(1, 0)
            .reshape((cfg["hidden_dim"], cfg["num_heads"], -1))
            .numpy()
        )
        keras_hub_model.get_layer(
            f"transformer_layer_{i}"
        )._self_attention_layer._key_dense.bias.assign(
            hf_wts[f"transformer.layer.{i}.attention.k_lin.bias"]
            .reshape((cfg["num_heads"], -1))
            .numpy()
        )

        keras_hub_model.get_layer(
            f"transformer_layer_{i}"
        )._self_attention_layer._value_dense.kernel.assign(
            hf_wts[f"transformer.layer.{i}.attention.v_lin.weight"]
            .transpose(1, 0)
            .reshape((cfg["hidden_dim"], cfg["num_heads"], -1))
            .numpy()
        )
        keras_hub_model.get_layer(
            f"transformer_layer_{i}"
        )._self_attention_layer._value_dense.bias.assign(
            hf_wts[f"transformer.layer.{i}.attention.v_lin.bias"]
            .reshape((cfg["num_heads"], -1))
            .numpy()
        )

        keras_hub_model.get_layer(
            f"transformer_layer_{i}"
        )._self_attention_layer._output_dense.kernel.assign(
            hf_wts[f"transformer.layer.{i}.attention.out_lin.weight"]
            .transpose(1, 0)
            .reshape((cfg["num_heads"], -1, cfg["hidden_dim"]))
            .numpy()
        )
        keras_hub_model.get_layer(
            f"transformer_layer_{i}"
        )._self_attention_layer._output_dense.bias.assign(
            hf_wts[f"transformer.layer.{i}.attention.out_lin.bias"].numpy()
        )

        keras_hub_model.get_layer(
            f"transformer_layer_{i}"
        )._self_attention_layer_norm.gamma.assign(
            hf_wts[f"transformer.layer.{i}.sa_layer_norm.weight"].numpy()
        )
        keras_hub_model.get_layer(
            f"transformer_layer_{i}"
        )._self_attention_layer_norm.beta.assign(
            hf_wts[f"transformer.layer.{i}.sa_layer_norm.bias"].numpy()
        )

        keras_hub_model.get_layer(
            f"transformer_layer_{i}"
        )._feedforward_intermediate_dense.kernel.assign(
            hf_wts[f"transformer.layer.{i}.ffn.lin1.weight"]
            .transpose(1, 0)
            .numpy()
        )
        keras_hub_model.get_layer(
            f"transformer_layer_{i}"
        )._feedforward_intermediate_dense.bias.assign(
            hf_wts[f"transformer.layer.{i}.ffn.lin1.bias"].numpy()
        )

        keras_hub_model.get_layer(
            f"transformer_layer_{i}"
        )._feedforward_output_dense.kernel.assign(
            hf_wts[f"transformer.layer.{i}.ffn.lin2.weight"]
            .transpose(1, 0)
            .numpy()
        )
        keras_hub_model.get_layer(
            f"transformer_layer_{i}"
        )._feedforward_output_dense.bias.assign(
            hf_wts[f"transformer.layer.{i}.ffn.lin2.bias"].numpy()
        )

        keras_hub_model.get_layer(
            f"transformer_layer_{i}"
        )._feedforward_layer_norm.gamma.assign(
            hf_wts[f"transformer.layer.{i}.output_layer_norm.weight"].numpy()
        )
        keras_hub_model.get_layer(
            f"transformer_layer_{i}"
        )._feedforward_layer_norm.beta.assign(
            hf_wts[f"transformer.layer.{i}.output_layer_norm.bias"].numpy()
        )

    # Save the model.
    print(f"\n-> Save KerasHub model weights to `{FLAGS.preset}.h5`.")
    keras_hub_model.save_weights(f"{FLAGS.preset}.h5")

    return keras_hub_model


def check_output(
    keras_hub_preprocessor,
    keras_hub_model,
    hf_tokenizer,
    hf_model,
):
    print("\n-> Check the outputs.")
    sample_text = ["cricket is awesome, easily the best sport in the world!"]

    # KerasHub
    keras_hub_inputs = keras_hub_preprocessor(tf.constant(sample_text))
    keras_hub_output = keras_hub_model.predict(keras_hub_inputs)

    # HF
    hf_inputs = hf_tokenizer(
        sample_text, padding="max_length", return_tensors="pt"
    )
    hf_output = hf_model(**hf_inputs).last_hidden_state

    print("KerasHub output:", keras_hub_output[0, 0, :10])
    print("HF output:", hf_output[0, 0, :10])
    print("Difference:", np.mean(keras_hub_output - hf_output.detach().numpy()))

    # Show the MD5 checksum of the model weights.
    print("Model md5sum: ", get_md5_checksum(f"./{FLAGS.preset}.h5"))


def main(_):
    hf_model_name = PRESET_MAP[FLAGS.preset]

    download_files(hf_model_name)

    keras_hub_preprocessor, hf_tokenizer = define_preprocessor(hf_model_name)

    print("\n-> Load KerasHub model.")
    keras_hub_model = keras_hub.models.DistilBertBackbone.from_preset(
        FLAGS.preset, load_weights=False
    )

    print("\n-> Load HF model.")
    hf_model = transformers.AutoModel.from_pretrained(hf_model_name)
    hf_model.eval()

    keras_hub_model = convert_checkpoints(keras_hub_model, hf_model)

    check_output(
        keras_hub_preprocessor,
        keras_hub_model,
        hf_tokenizer,
        hf_model,
    )


if __name__ == "__main__":
    flags.mark_flag_as_required("preset")
    app.run(main)
