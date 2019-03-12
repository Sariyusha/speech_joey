# coding: utf-8
"""
Data module
"""
import sys
import os
import os.path

from torchtext.datasets import TranslationDataset
from torchtext import data
from torchtext.data import Dataset

from joeynmt.constants import UNK_TOKEN, EOS_TOKEN, BOS_TOKEN, PAD_TOKEN
from joeynmt.vocabulary import build_vocab


def load_data(cfg: dict):
    """
    Load train, dev and test data as specified in configuration.

    :param cfg: configuration dictionary
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
                                    <= max_sent_length
                                    and len(vars(x)['trg'])
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


class MonoDataset(Dataset):
    """Defines a dataset for machine translation without targets."""

    @staticmethod
    def sort_key(ex):
        return len(ex.src)

    def __init__(self, path: str, ext: str, field: str, **kwargs):
        """
        Create a monolingual dataset (=only sources) given path and field.

        :param path: Prefix of path to the data file
        :param ext: Containing the extension to path for this language.
        :param field: Containing the fields that will be used for data.
        :param kwargs: Passed to the constructor of
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


def load_audio_data(cfg: dict):
    """
    Load train, dev and test audio data as specified in configuration.

    :param cfg: configuration dictionary
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

    #pylint: disable=unnecessary-lambda
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
                              <= max_audio_length
                              and len(vars(x)['trg'])
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
                            dataset=train_data, vocab_file=trg_vocab_file)
    src_vocab = trg_vocab

    dev_data = AudioDataset(path=dev_path, text_ext="." + audio_lang,
                                  audio_ext=".txt", field=trg_field, num=mfcc_number,
                                  char_level=char, train=False)
    test_data = None
    if test_path is not None:
        # check if target exists
        if os.path.isfile(test_path + "." + audio_lang):
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

    @staticmethod
    def sort_key(ex):
        return len(ex.src)

    def __init__(self, path: str, audio_ext: str, **kwargs):
        """
        Create an AudioDataset given path and field.

        Arguments:
            path: Prefix of path to the data file
            audio_ext: Containing the extension to path for the audio files.
            Remaining keyword arguments: Passed to the constructor of
                data.Dataset.
        """
        audio_field = data.RawField()
        fields = [('src', audio_field)]

        #TODO fix / extend fields here

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