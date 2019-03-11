# coding: utf-8
"""
Collection of helper functions
"""
import copy
import glob
import os
import os.path
import sys
import torchaudio as ta
import librosa

from collections import Counter
from logging import Logger
from typing import Callable
import numpy as np
import yaml

import torch
from torch import nn

from torchtext.datasets import TranslationDataset
from torchtext import data
from torchtext.data import Dataset

from joeynmt.constants import UNK_TOKEN, DEFAULT_UNK_ID, \
    EOS_TOKEN, BOS_TOKEN, PAD_TOKEN
from joeynmt.vocabulary import Vocabulary
from joeynmt.plotting import plot_heatmap


def log_cfg(cfg: dict, logger: Logger, prefix: str = "cfg"):
    """
    Write configuration to log.

    :param cfg: configuration to log
    :param logger: logger that defines where log is written to
    :param prefix: prefix for logging
    :return:
    """
    for k, v in cfg.items():
        if isinstance(v, dict):
            p = '.'.join([prefix, k])
            log_cfg(v, logger, prefix=p)
        else:
            p = '.'.join([prefix, k])
            logger.info("{:34s} : {}".format(p, v))


def build_vocab(field: str, max_size: int, min_freq: int, dataset: Dataset,
                vocab_file: str = None):
    """
    Builds vocabulary for a torchtext `field`.

    :param field: attribute e.g. "src"
    :param max_size: maximum size of vocabulary
    :param min_freq: minimum frequency for an item to be included
    :param dataset: dataset to load data for field from
    :param vocab_file: file to store the vocabulary
    :return:
    """

    # special symbols
    specials = [UNK_TOKEN, PAD_TOKEN, BOS_TOKEN, EOS_TOKEN]

    if vocab_file is not None:
        # load it from file
        vocab = Vocabulary(file=vocab_file)
        vocab.add_tokens(specials)
    else:
        # create newly
        def filter_min(counter, min_freq):
            """ Filter counter by min frequency """
            filtered_counter = Counter({t: c for t, c in counter.items()
                                        if c >= min_freq})
            return filtered_counter

        def sort_and_cut(counter, limit):
            """ Cut counter to most frequent,
            sorted numerically and alphabetically"""
            # sort by frequency, then alphabetically
            tokens_and_frequencies = sorted(counter.items(),
                                            key=lambda tup: tup[0])
            tokens_and_frequencies.sort(key=lambda tup: tup[1], reverse=True)
            vocab_tokens = [i[0] for i in tokens_and_frequencies[:limit]]
            return vocab_tokens

        tokens = []
        for i in dataset.examples:
            if field == "src":
                tokens.extend(i.src)
            elif field == "trg":
                tokens.extend(i.trg)

        counter = Counter(tokens)
        if min_freq > -1:
            counter = filter_min(counter, min_freq)
        vocab_tokens = specials + sort_and_cut(counter, max_size)
        assert vocab_tokens[DEFAULT_UNK_ID()] == UNK_TOKEN
        assert len(vocab_tokens) <= max_size + len(specials)
        vocab = Vocabulary(tokens=vocab_tokens)

    # check for all except for UNK token whether they are OOVs
    for s in specials[1:]:
        assert not vocab.is_unk(s)

    return vocab


def array_to_sentence(array: np.array, vocabulary: Vocabulary, cut_at_eos=True):
    """
    Converts an array of IDs to a sentence, optionally cutting the result
    off at the end-of-sequence token.

    :param array: 1D array containing indices
    :param vocabulary: defines mapping of indices to tokens
    :param cut_at_eos: cut the decoded sentences at the first <eos>
    :return:
    """
    sentence = []
    for i in array:
        s = vocabulary.itos[i]
        if cut_at_eos and s == EOS_TOKEN:
            break
        sentence.append(s)
    return sentence


def arrays_to_sentences(arrays: np.array, vocabulary: Vocabulary,
                        cut_at_eos=True):
    """
    Convert multiple arrays containing sequences of token IDs to their
    sentences, optionally cutting them off at the end-of-sequence token.

    :param arrays: 2D array containing indices
    :param vocabulary: defines mapping of indices to tokens
    :param cut_at_eos: cut the decoded sentences at the first <eos>
    :return:
    """
    sentences = []
    for array in arrays:
        sentences.append(
            array_to_sentence(array=array, vocabulary=vocabulary,
                              cut_at_eos=cut_at_eos))
    return sentences


def clones(module: nn.Module, n: int):
    """
    Produce N identical layers. Transformer helper function.

    :param module: the module to clone
    :param n: clone this many times
    :return:
    """
    return nn.ModuleList([copy.deepcopy(module) for _ in range(n)])


def subsequent_mask(size: int):
    """
    Mask out subsequent positions (to prevent attending to future positions)
    Transformer helper function.

    :param size:
    :return:
    """
    attn_shape = (1, size, size)
    mask = np.triu(np.ones(attn_shape), k=1).astype('uint8')
    return torch.from_numpy(mask) == 0


def log_data_info(train_data: Dataset, valid_data: Dataset, test_data: Dataset,
                  src_vocab: Vocabulary, trg_vocab: Vocabulary,
                  logging_function: Callable[[str], None]):
    """
    Log statistics of data and vocabulary.

    :param train_data:
    :param valid_data:
    :param test_data:
    :param src_vocab:
    :param trg_vocab:
    :param logging_function:
    :return:
    """
    logging_function(
        "Data set sizes: \n\ttrain %d,\n\tvalid %d,\n\ttest %d",
            len(train_data), len(valid_data),
            len(test_data) if test_data is not None else 0)

    logging_function("First training example:\n\t[SRC] %s\n\t[TRG] %s",
        " ".join(vars(train_data[0])['src']),
        " ".join(vars(train_data[0])['trg']))

    logging_function("First 10 words (src): %s", " ".join(
        '(%d) %s' % (i, t) for i, t in enumerate(src_vocab.itos[:10])))
    logging_function("First 10 words (trg): %s", " ".join(
        '(%d) %s' % (i, t) for i, t in enumerate(trg_vocab.itos[:10])))

    logging_function("Number of Src words (types): %d", len(src_vocab))
    logging_function("Number of Trg words (types): %d", len(trg_vocab))


def load_data(cfg):
    """
    Load train, dev and test data as specified in ccnfiguration.

    :param cfg:
    :return:
    """
    # load data from files
    data_cfg = cfg["data"]
    src_lang = data_cfg["src"]
    trg_lang = data_cfg["trg"]
    train_path = data_cfg["train"]
    dev_path = data_cfg["dev"]
    test_path = data_cfg.get("test", None)
    level = data_cfg["level"]
    lowercase = data_cfg["lowercase"]
    max_sent_length = data_cfg["max_sent_length"]

    #pylint: disable=unnecessary-lambda
    if level == "char":
        tok_fun = lambda s: list(s)
    else:  # bpe or word, pre-tokenized
        tok_fun = lambda s: s.split()

    src_field = data.Field(init_token=None, eos_token=EOS_TOKEN,
                           pad_token=PAD_TOKEN, tokenize=tok_fun,
                           batch_first=True, lower=lowercase,
                           unk_token=UNK_TOKEN,
                           include_lengths=True)

    trg_field = data.Field(init_token=BOS_TOKEN, eos_token=EOS_TOKEN,
                           pad_token=PAD_TOKEN, tokenize=tok_fun,
                           unk_token=UNK_TOKEN,
                           batch_first=True, lower=lowercase,
                           include_lengths=True)
    train_data = TranslationDataset(path=train_path,
                                    exts=("." + src_lang, "." + trg_lang),
                                    fields=(src_field, trg_field),
                                    filter_pred=
                                    lambda x: len(vars(x)['src'])
                                              <= max_sent_length and
                                              len(vars(x)['trg'])
                                              <= max_sent_length)
   
    max_size = data_cfg.get("voc_limit", sys.maxsize)
    min_freq = data_cfg.get("voc_min_freq", 1)
    src_vocab_file = data_cfg.get("src_vocab", None)
    trg_vocab_file = data_cfg.get("trg_vocab", None)

    src_vocab = build_vocab(field="src", min_freq=min_freq, max_size=max_size,
                            dataset=train_data, vocab_file=src_vocab_file)
    trg_vocab = build_vocab(field="trg", min_freq=min_freq, max_size=max_size,
                            dataset=train_data, vocab_file=trg_vocab_file)
    dev_data = TranslationDataset(path=dev_path,
                                  exts=("." + src_lang, "." + trg_lang),
                                  fields=(src_field, trg_field))
    test_data = None
    if test_path is not None:
        # check if target exists
        if os.path.isfile(test_path + "." + trg_lang):
            test_data = TranslationDataset(
                path=test_path, exts=("." + src_lang, "." + trg_lang),
                fields=(src_field, trg_field))
        else:
            # no target is given -> create dataset from src only
            test_data = MonoDataset(path=test_path, ext="." + src_lang,
                                    field=(src_field))
    src_field.vocab = src_vocab
    trg_field.vocab = trg_vocab
    return train_data, dev_data, test_data, src_vocab, trg_vocab


class MonoDataset(Dataset):
    """Defines a dataset for machine translation without targets."""


    @staticmethod
    def sort_key(ex):
        return len(ex.src)

    def __init__(self, path, ext, field, **kwargs):
        """Create a MonoDataset given path and field.

        Arguments:
            path: Prefix of path to the data file
            ext: Containing the extension to path for this language.
            field: Containing the fields that will be used for data
            Remaining keyword arguments: Passed to the constructor of
                data.Dataset.
        """
        fields = [('src', field)]

        src_path = os.path.expanduser(path + ext)

        examples = []
        with open(src_path) as src_file:
            for src_line in src_file:
                src_line = src_line.strip()
                if src_line != '':
                    examples.append(data.Example.fromlist(
                        [src_line], fields))

        super(MonoDataset, self).__init__(examples, fields, **kwargs)


def load_audio_data(cfg):
    """
    Load train, dev and test audio data as specified in configuration.

    :param cfg:
    :return:
    """
    # load data from files
    data_cfg = cfg["data"]
    src_lang = data_cfg["src"]
    trg_lang = data_cfg["trg"]
    if data_cfg["audio"] == "src":
        audio_lang = src_lang
    else:
        audio_lang = trg_lang
    train_path = data_cfg["train"]
    dev_path = data_cfg["dev"]
    test_path = data_cfg.get("test", None)
    level = data_cfg["level"]
    lowercase = data_cfg["lowercase"]
    max_sent_length = data_cfg["max_sent_length"]
    max_audio_length = data_cfg["max_audio_length"]
    mfcc_number = cfg["model"]["encoder"]["embeddings"]["embedding_dim"]

    if level == "char":
        tok_fun = lambda s: list(s)
        char = True
    else:  # bpe or word, pre-tokenized
        tok_fun = lambda s: s.split()
        char = False

    trg_field = data.Field(init_token=None, eos_token=EOS_TOKEN,
                        pad_token=PAD_TOKEN, tokenize=tok_fun,
                        batch_first=True, lower=lowercase,
                        unk_token=UNK_TOKEN,
                        include_lengths=True)

    train_data = AudioDataset(path=train_path, text_ext="." + audio_lang,
                              audio_ext=".txt", field=trg_field, num=mfcc_number,
                              char_level=char, train=True, filter_pred=
                              lambda x: len(vars(x)['src'])
                                        <= max_audio_length and
                                        len(vars(x)['trg'])
                                        <= max_sent_length)

    #for x in range(len(train_data)):
        #print(len(train_data.gettext(x)))
        #print(train_data[x])
        #print(train_data.gettext(x))

    max_size = data_cfg.get("voc_limit", sys.maxsize)
    min_freq = data_cfg.get("voc_min_freq", 1)
    trg_vocab_file = data_cfg.get(audio_lang + "_vocab", None)
    #trg_vocab_file = data_cfg.get(data_cfg["vocab"], None)
    trg_vocab = build_vocab(field="trg", min_freq=min_freq, max_size=max_size,
                            data=train_data, vocab_file=trg_vocab_file)
    src_vocab = trg_vocab 
    
    dev_data = AudioDataset(path=dev_path, text_ext="." + audio_lang,
                                  audio_ext=".txt", field=trg_field, num=mfcc_number, 
                                  char_level=char, train=False)
    test_data = None
    if test_path is not None:
        # check if target exists
        if os.path.isfile(test_path+"."+audio_lang):
            test_data = AudioDataset(
                path=test_path, text_ext="." + audio_lang,
                audio_ext=".txt", field=trg_field, num=mfcc_number, 
                char_level=char, train=False)
        else:
            # no target is given -> create dataset from src only
            test_data = MonoAudioDataset(path=test_path, audio_ext=".txt")
    trg_field.vocab = trg_vocab
    return train_data, dev_data, test_data, src_vocab, trg_vocab


class AudioDataset(TranslationDataset):
    """Defines a dataset for speech recognition/translation."""

    def __init__(self, path, text_ext, audio_ext, field, num, char_level, train, **kwargs):
        """Create an AudioDataset given path and fields.

        Arguments:
            path: Prefix of path to the data file
            ext: Containing the extension to path for the wanted language.
            fields: Containing the fields that will be used for data
            Remaining keyword arguments: Passed to the constructor of
                data.Dataset.
        """
        audio_field = data.RawField()
        fields = [('trg', field), ('audio', audio_field), ('audio2', audio_field), ('mfcc', audio_field), ('src', field)]

        text_path = os.path.expanduser(path + text_ext)
        audio_path = os.path.expanduser(path + audio_ext)
        examples = []
        maxi = 1
        mini = 10
        summa = 0 
        count = 0
        log_path = os.path.expanduser(path + '_length_statistics')
        length_info = open(log_path, 'a')

        if len(open(text_path).read().splitlines()) != len(open(audio_path).read().splitlines()):
            raise IndexError('The size of the text and audio dataset differs.')
        else:
            with open(text_path) as text_file, open(audio_path) as audio_file:
                for text_line, audio_line in zip(text_file, audio_file):
                    text_line = text_line.strip()
                    audio_line = audio_line.strip()
                    sound, sample_rate = ta.load(audio_line)
                    y, sr = librosa.load(audio_line, sr=None)
                    features = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=num)
                    featuresT = features.T
                    #print(features[:, 0]) # print mfccs for the first window
                    featureS = torch.Tensor(featuresT)
                    #print(featureS.size, " MFCC_T", featureS.shape, " SHAPE", featureS.shape[0], " DIMENSION")
                    if char_level : 
                        audio_dummy = "a" * (featuresT.shape[0] - 1) #generate a line with <unk> of given size
                    else :
                        audio_dummy = "a " * (featuresT.shape[0] - 1) #generate a line with <unk> of given size
                    check = featuresT.shape[0] // (len(text_line) + 1)
                    if train :
                        if text_line != '' and audio_line != '' and os.path.getsize(audio_line) > 44 and check < 10 :
                            examples.append(data.Example.fromlist([text_line, sound, y, featureS, audio_dummy], fields))
                            #length_info.write('COMPARE AUDIO LENGTH {0} TO TEXT LENGTH {1} \n'.format(featuresT.shape[0], len(text_line) + 1))
                            if check > maxi: 
                                maxi = check 
                            if check < mini:
                                mini = check
                            summa += check 
                            count += 1
                    else: 
                        examples.append(data.Example.fromlist([text_line, sound, y, featureS, audio_dummy], fields))
                        if check > maxi:
                            maxi = check
                        if check < mini:
                            mini = check
                        summa += check
                        count += 1
        length_info.write('mini={0}, maxi={1}, mean={2} \n'.format(mini, maxi, summa/count))
        length_info.close()
        super(TranslationDataset, self).__init__(examples, fields, **kwargs)

    def __len__(self):
        return len(self.examples)

    def gettext(self, index):
        return self.examples[index].trg

    def getaudio(self, index):
        return self.examples[index].audio


class MonoAudioDataset(TranslationDataset):
    """Defines a dataset for speech recognition/translation without targets."""

    def __init__(self, path, audio_ext, **kwargs):
        """Create an AudioDataset given path and field.

        Arguments:
            path: Prefix of path to the data file
            audio_ext: Containing the extension to path for the audio files.
            fields: Containing the fields that will be used for data
            Remaining keyword arguments: Passed to the constructor of
                data.Dataset.
        """
        audio_field = data.RawField()
        fields = [('src', audio_field)]

        #TODO extend fields here

        audio_path = os.path.expanduser(path + audio_ext)
        examples = []

        with open(audio_path) as audio_file:
            for audio_line in audio_file:
                audio_line = audio_line.strip()
                sound, sample_rate = ta.load(audio_line)
                if audio_line != '' and os.path.getsize(audio_line) > 44 :
                    examples.append(data.Example.fromlist([sound], fields))
        super(TranslationDataset, self).__init__(examples, fields, **kwargs)

    def __len__(self):
        return len(self.examples)


def load_config(path="configs/default.yaml"):
    """
    Loads and parses a YAML configuration file.

    :param path:
    :return:
    """
    with open(path, 'r') as ymlfile:
        cfg = yaml.load(ymlfile)
    return cfg


def bpe_postprocess(string):
    """
    Post-processor for BPE output. Recombines BPE-split tokens.

    :param string:
    :return:
    """
    return string.replace("@@ ", "")


def store_attention_plots(attentions, targets, sources, output_prefix,
                          idx):
    """
    Saves attention plots.

    :param attentions:
    :param targets:
    :param sources:
    :param output_prefix:
    :param idx:
    :return:
    """
    for i in idx:
        plot_file = "{}.{}.pdf".format(output_prefix, i)
        src = sources[i]
        trg = targets[i]
        attention_scores = attentions[i].T
        try:
            plot_heatmap(scores=attention_scores, column_labels=trg,
                         row_labels=src, output_path=plot_file)
        # pylint: disable=bare-except
        except:
            print("Couldn't plot example {}: src len {}, trg len {}, "
                  "attention scores shape {}".format(i, len(src), len(trg),
                                                     attention_scores.shape))
            continue


def get_latest_checkpoint(ckpt_dir):
    """
    Returns the latest checkpoint (by time) from the given directory.

    :param ckpt_dir:
    :return:
    """
    list_of_files = glob.glob("{}/*.ckpt".format(ckpt_dir))
    latest_file = max(list_of_files, key=os.path.getctime)
    return latest_file


def load_model_from_checkpoint(path, use_cuda=True):
    """
    Load model from saved checkpoint.

    :param path:
    :param use_cuda:
    :return:
    """
    assert os.path.isfile(path), "Checkpoint %s not found" % path
    model_checkpoint = torch.load(path,
                                  map_location='cuda' if use_cuda else 'cpu')
    return model_checkpoint


def make_data_iter(dataset, batch_size, train=False, shuffle=False):
    """
    Returns a torchtext iterator for a torchtext dataset.

    :param dataset:
    :param batch_size:
    :param train:
    :param shuffle:
    :return:
    """
    if train:
        # optionally shuffle and sort during training
        data_iter = data.BucketIterator(
            repeat=False, sort=False, dataset=dataset,
            batch_size=batch_size, train=True, sort_within_batch=True,
            sort_key=lambda x: len(x.src), shuffle=shuffle)
    else:
        # don't sort/shuffle for validation/inference
        data_iter = data.Iterator(
            repeat=False, dataset=dataset, batch_size=batch_size,
            train=False, sort=False)

    return data_iter


# from onmt
def tile(x, count, dim=0):
    """
    Tiles x on dimension dim count times. From OpenNMT. Used for beam search.

    :param x:
    :param count:
    :param dim:
    :return:
    """
    if isinstance(x, tuple):
        h, c = x
        return tile(h, count, dim=dim), tile(c, count, dim=dim)

    perm = list(range(len(x.size())))
    if dim != 0:
        perm[0], perm[dim] = perm[dim], perm[0]
        x = x.permute(perm).contiguous()
    out_size = list(x.size())
    out_size[0] *= count
    batch = x.size(0)
    x = x.view(batch, -1) \
        .transpose(0, 1) \
        .repeat(count, 1) \
        .transpose(0, 1) \
        .contiguous() \
        .view(*out_size)
    if dim != 0:
        x = x.permute(perm).contiguous()
    return x


def freeze_params(module):
    """
    Freeze the parameters of this module,
    i.e. do not update them during training

    :param module:
    :return:
    """
    for _, p in module.named_parameters():
        p.requires_grad = False
