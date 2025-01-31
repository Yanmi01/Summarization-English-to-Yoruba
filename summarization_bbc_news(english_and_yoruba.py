# -*- coding: utf-8 -*-
"""Summarization: BBC news(English and Yoruba.ipynb

Automatically generated by Colab.

Original file is located at
    https://colab.research.google.com/drive/1n2hCiPd5wLa8UEJwlqV0t_KPpPtFxA5H
"""

!pip install datasets evaluate transformers[sentencepiece]
!pip install accelerate
!apt install git-lfs

!git config --global user.email "egbewaleyanmife@gmail.com"
!git config --global user.name "Yanmi01"

from huggingface_hub import notebook_login

notebook_login()

from datasets import load_dataset

# Load the Yorùbá portion of the XL-Sum dataset
yor_dataset = load_dataset("GEM/xlsum", "yoruba", trust_remote_code=True)

# Load the English portion of the XL-Sum dataset
eng_dataset = load_dataset("GEM/xlsum", "english", trust_remote_code=True)

yor_dataset

eng_dataset

def show_samples(dataset, num_samples=3, seed=42):
    sample = dataset["train"].shuffle(seed=seed).select(range(num_samples))
    for example in sample:
        print(f"\n'>> Title: {example['title']}'")
        print(f"'>> Review: {example['target']}'")

show_samples(yor_dataset)

show_samples(eng_dataset)

"""Since English dataset is much larger than yoruba, we'll downsample the english dataset to make both balanced"""

from datasets import concatenate_datasets, DatasetDict

eng_dataset_train = eng_dataset['train'].shuffle(seed=42).select(range(6350))

eng_dataset_test = eng_dataset['test'].shuffle(seed=42).select(range(793))

eng_dataset_val = eng_dataset['validation'].shuffle(seed=42).select(range(793))

eng_dataset_downsampled = DatasetDict({
    'train': eng_dataset_train,
    'test': eng_dataset_test,
    'validation': eng_dataset_val
})

eng_dataset_downsampled

from datasets import concatenate_datasets, DatasetDict

sum_dataset = DatasetDict()

for split in eng_dataset_downsampled.keys():
    sum_dataset[split] = concatenate_datasets(
        [eng_dataset_downsampled[split], yor_dataset[split]]
    )
    sum_dataset[split] = sum_dataset[split].shuffle(seed=42)

# Peek at a few examples
show_samples(sum_dataset)

sum_dataset

less_dataset = sum_dataset.filter(lambda x: len(x["title"].split()) < 2)

less_dataset

from transformers import AutoTokenizer

model_checkpoint = "google/mt5-small"
tokenizer = AutoTokenizer.from_pretrained(model_checkpoint)

inputs = tokenizer("I loved reading the Hunger Games!")
inputs

tokenizer.convert_ids_to_tokens(inputs.input_ids)

max_input_length = 512
max_target_length = 30


def preprocess_function(examples):
    model_inputs = tokenizer(
        examples["target"],
        max_length=max_input_length,
        truncation=True,
    )
    labels = tokenizer(
        examples["title"], max_length=max_target_length, truncation=True
    )
    model_inputs["labels"] = labels["input_ids"]
    return model_inputs

tokenized_datasets = sum_dataset.map(preprocess_function, batched=True)

generated_summary = "I absolutely loved reading the Hunger Games"
reference_summary = "I loved reading the Hunger Games"

""" Here, our evaluation metric will be ROUGE score (Recall-Oriented Understudy for Gisting Evaluation). The basic idea behind this metric is to compare a generated summary against a set of reference summaries that are typically created by humans.


"""

!pip install rouge_score

import evaluate

rouge_score = evaluate.load("rouge")

from urllib.parse import uses_fragment
scores = rouge_score.compute(
    predictions=[generated_summary], references=[reference_summary], use_aggregator=True
)
scores

import numpy as np
np.median(scores["rouge1"])

!pip install rouge-score
from rouge_score import rouge_scorer

scorer = rouge_scorer.RougeScorer(['rouge1', 'rouge2', 'rougeL', 'rougeLsum'], use_stemmer=True)
scores = scorer.score(reference_summary, generated_summary)

scores

!pip install nltk

import nltk

nltk.download("punkt")
nltk.download('punkt_tab')

from nltk.tokenize import sent_tokenize


def three_sentence_summary(text):
    return "\n".join(sent_tokenize(text)[:3])


print(three_sentence_summary(sum_dataset["train"][1]["target"]))

def evaluate_baseline(dataset, metric):
    summaries = [three_sentence_summary(text) for text in dataset["target"]]
    return metric.compute(predictions=summaries, references=dataset["title"])

import pandas as pd

score = evaluate_baseline(sum_dataset["validation"], rouge_score)

rouge_names = ["rouge1", "rouge2", "rougeL", "rougeLsum"]
rouge_dict = dict((rn, round(score[rn] * 100, 2)) for rn in rouge_names)
rouge_dict

from transformers import AutoModelForSeq2SeqLM

model = AutoModelForSeq2SeqLM.from_pretrained(model_checkpoint)

from transformers import Seq2SeqTrainingArguments

batch_size = 8
num_train_epochs = 8
# Show the training loss with every epoch
logging_steps = len(tokenized_datasets["train"]) // batch_size
model_name = model_checkpoint.split("/")[-1]

args = Seq2SeqTrainingArguments(
    output_dir=f"{model_name}mt5-finetuned-on-en-yor-BBC-news",
    evaluation_strategy="epoch",
    learning_rate=5.6e-5,
    per_device_train_batch_size=batch_size,
    per_device_eval_batch_size=batch_size,
    weight_decay=0.01,
    save_total_limit=3,
    num_train_epochs=num_train_epochs,
    predict_with_generate=True,
    logging_steps=logging_steps,
    push_to_hub=True,
)

import numpy as np


def compute_metrics(eval_pred):
    predictions, labels = eval_pred
    # Decode generated summaries into text
    # Clip predictions to the valid token ID range before decoding
    predictions = np.clip(predictions, 0, tokenizer.vocab_size - 1)
    decoded_preds = tokenizer.batch_decode(predictions, skip_special_tokens=True)
    # Replace -100 in the labels as we can't decode them
    labels = np.where(labels != -100, labels, tokenizer.pad_token_id)
    # Decode reference summaries into text
    decoded_labels = tokenizer.batch_decode(labels, skip_special_tokens=True)
    # ROUGE expects a newline after each sentence
    decoded_preds = ["\n".join(sent_tokenize(pred.strip())) for pred in decoded_preds]
    decoded_labels = ["\n".join(sent_tokenize(label.strip())) for label in decoded_labels]
    # Compute ROUGE scores
    result = rouge_score.compute(
        predictions=decoded_preds, references=decoded_labels, use_stemmer=True
    )
    # Extract the median scores
    result = {key: value * 100 for key, value in result.items()}
    return {k: round(v, 4) for k, v in result.items()}

from transformers import DataCollatorForSeq2Seq

data_collator = DataCollatorForSeq2Seq(tokenizer, model=model)

tokenized_datasets = tokenized_datasets.remove_columns(
    sum_dataset["train"].column_names
)

features = [tokenized_datasets["train"][i] for i in range(2)]
data_collator(features)

from transformers import Seq2SeqTrainer

trainer = Seq2SeqTrainer(
    model,
    args,
    train_dataset=tokenized_datasets["train"],
    eval_dataset=tokenized_datasets["validation"],
    data_collator=data_collator,
    tokenizer=tokenizer,
    compute_metrics=compute_metrics,
)

trainer.train()

trainer.evaluate()

trainer.push_to_hub(commit_message="Training complete", tags="summarization")

from transformers import pipeline

hub_model_id = "Yanmife/mt5-smallmt5-finetuned-on-en-yor-BBC-news"
summarizer = pipeline("summarization", model=hub_model_id)

def print_summary(idx):
    review = sum_dataset["test"][idx]["target"]
    title = sum_dataset["test"][idx]["title"]
    summary = summarizer(sum_dataset["test"][idx]["target"])[0]["summary_text"]
    print(f"'>>> Review: {review}'")
    print(f"\n'>>> Title: {title}'")
    print(f"\n'>>> Summary: {summary}'")

print_summary(100)

print_summary(0)