#!/usr/bin/env python
# coding: utf-8


import json
from sklearn_crfsuite import CRF
import numpy as np
from scipy.stats import entropy
from nltk import word_tokenize, pos_tag
import random
import pickle
import os
from bs4 import BeautifulSoup
from bs4 import Tag
from collections import Counter

from flask import Flask
from flask import request
from jinja2 import Template
import pandas as pd
from nltk import download as nltk_download

nltk_download('punkt')
nltk_download('averaged_perceptron_tagger')


class BaseNerTagger:
    """
    A utility class for NER Tagging.
    """

    def __init__(self, unlabelled, labelled=None, data_directory=''):
        """
        Initialize with a list of unlabelled strings and/or list of tagged tuples.
        Args:
            unlabelled: list of strings
            labelled: list of {list of tuples [(token, pos_tag, tag), ...]}
            data_directory: Default directory to save all data
        """
        if unlabelled is None:
            self.unlabelled = None
        else:
            self.unlabelled = [{'raw': BaseNerTagger._get_pos_tagged_example(text)} for text in unlabelled]
        if labelled is None:
            labelled = []
        self.labelled = labelled
        self.model = None

        self.data_directory = os.path.join(data_directory, 'NER_Data')
        os.makedirs(self.data_directory, exist_ok=True)


    @staticmethod
    def _get_pos_tagged_example(text):
        tokens = word_tokenize(text)
        toret = pos_tag(tokens)
        return toret

    @staticmethod
    def _is_alpha_and_numeric(string):
        """
        Checks whether the string is alpha/numeric or both
        Args:
            string: text string

        Returns: alpha numeric class [DIGIT/ALPHA_UPPER/ALPHA_LOWER/ALPHA/ALPHA_NUM/EMPTY]

        """
        toret = ''
        if string.isdigit():
            toret = 'DIGIT'
        elif string.isalpha():
            if string.isupper():
                toret = 'ALPHA_UPPER'
            elif string.islower():
                toret = 'ALPHA_LOWER'
            else:
                toret = 'ALPHA'
        elif len(string) > 0:
            toks = [string[0], string[-1]]
            alphanum = 0
            for tok in toks:
                if tok.isdigit():
                    alphanum += 1
                elif tok.isalpha():
                    alphanum -= 1
            if alphanum == 0:
                toret = 'ALPHA_NUM'
        else:
            toret = 'EMPTY'

        return toret

    @staticmethod
    def _word2features(sent, i):
        """
        Calculate features for each word in the sentence
        Args:
            sent: List of words in the sentence
            i: i'th word in the sentence

        Returns:

        """

        word = sent[i][0]
        postag = sent[i][1]

        features = {
            'bias': 1.0,
            'word.lower()': word.lower(),
            'word[-3:]': word[-3:],
            'word[-2:]': word[-2:],
            'word.isupper()': word.isupper(),
            'word.istitle()': word.istitle(),
            'word.isdigit()': word.isdigit(),
            'word.is_alphanum': BaseNerTagger._is_alpha_and_numeric(word),
            'postag': postag,
        }

        if i > 0:
            word = sent[i - 1][0]
            postag = sent[i - 1][1]
            features.update({
                '-1:word.lower()': word.lower(),
                '-1:word[-3:]': word[-3:],
                '-1:word[-2:]': word[-2:],
                '-1:word.istitle()': word.istitle(),
                '-1:word.isupper()': word.isupper(),
                '-1:postag': postag,
                '-1:word.is_alphanum': BaseNerTagger._is_alpha_and_numeric(word)
            })
        else:
            features['BOS'] = True

        if i > 1:
            word = sent[i - 2][0]
            postag = sent[i - 2][1]
            features.update({
                '-2:word.lower()': word.lower(),
                '-2:word[-3:]': word[-3:],
                '-2:word[-2:]': word[-2:],
                '-2:word.istitle()': word.istitle(),
                '-2:word.isupper()': word.isupper(),
                '-2:postag': postag,
                '-2:word.is_alphanum': BaseNerTagger._is_alpha_and_numeric(word)
            })

        if i < len(sent) - 1:
            word = sent[i + 1][0]
            postag = sent[i + 1][1]
            features.update({
                '+1:word.lower()': word.lower(),
                '+1:word[-3:]': word[-3:],
                '+1:word[-2:]': word[-2:],
                '+1:word.istitle()': word.istitle(),
                '+1:word.isupper()': word.isupper(),
                '+1:postag': postag,
                '+1:word.is_alphanum': BaseNerTagger._is_alpha_and_numeric(word)
            })
        else:
            features['EOS'] = True

        if i < len(sent) - 2:
            word = sent[i + 2][0]
            postag = sent[i + 2][1]
            features.update({
                '+2:word.lower()': word.lower(),
                '+2:word[-3:]': word[-3:],
                '+2:word[-2:]': word[-2:],
                '+2:word.istitle()': word.istitle(),
                '+2:word.isupper()': word.isupper(),
                '+2:postag': postag,
                '+2:word.is_alphanum': BaseNerTagger._is_alpha_and_numeric(word)
            })

        return features

    @staticmethod
    def _sent2features(sent):
        return [BaseNerTagger._word2features(sent, i) for i in range(len(sent))]

    @staticmethod
    def _sent2labels(sent):
        return [label for token, postag, label in sent]

    def _sent2tokens(sent):
        return [token for token, postag, label in sent]

    @staticmethod
    def _add_prediction_to_postagged_data(postagged, prediction):
        toret = []
        for i in range(len(postagged)):
            toret.append((postagged[i][0], postagged[i][1], prediction[i]))
        return toret

    @staticmethod
    def _get_prediction_uncertainity(pred, mode='max'):
        if len(pred) == 0:
            return 0
        un = []
        for tok in pred:
            probabilities = list(tok.values())
            ent = entropy(probabilities)
            un.append(ent)
        if mode == 'max':
            return max(un)
        elif mode == 'mean':
            return sum(un) / len(un)

    def get_new_random_example(self):
        """
        Returns a random example to be tagged. Used to bootstrap the model.
        Returns: Randomly selected text

        """
        self.current_example_index = random.randint(0, len(self.unlabelled) - 1)
        self.current_example = self.unlabelled[self.current_example_index]
        return self.current_example['raw']

    def get_new_random_predicted_example(self):
        """
        Returns a random example tagged by the currently tagged model.
        Returns: Text String

        """
        self.current_example_index = random.randint(0, len(self.unlabelled) - 1)
        self.current_example = self.unlabelled[self.current_example_index]
        raw = self.current_example['raw']
        features = BaseNerTagger._sent2features(raw)
        preds = self.model.predict_single(features)
        toret = BaseNerTagger._add_prediction_to_postagged_data(raw, preds)
        return toret

    def query_new_example(self, mode='max'):
        """
        Returns a new example based on the chosen active learning strategy.
        Args:
            mode: Active Learning Strategy
                - max (Default)
                - mean

        Returns:

        """
        if len(self.unlabelled) == 1:
            sample = [0]
        else:
            sample = np.random.randint(0, len(self.unlabelled) - 1, size=250).tolist()
        X = []
        for s in sample:
            example = self.unlabelled[s]
            if 'features' not in example:
                example['features'] = BaseNerTagger._sent2features(example['raw'])
            X.append(example['features'])
        preds = self.model.predict_marginals(X)
        uncertainities = [BaseNerTagger._get_prediction_uncertainity(pred, mode) for pred in preds]
        index = np.argmax(uncertainities)
        self.current_example_index = sample[index]
        self.current_example = self.unlabelled[self.current_example_index]
        raw = self.current_example['raw']
        features = self.current_example['features']
        preds = self.model.predict_single(features)
        toret = BaseNerTagger._add_prediction_to_postagged_data(raw, preds)
        return toret

    def update_model(self):
        """
        Updates the model with the currently labelled dataset
        Returns:

        """
        if self.model is None:
            self.model = CRF(
                algorithm='lbfgs',
                c1=0.1,
                c2=0.1,
                max_iterations=100,
                all_possible_transitions=True
            )
        X = [item['features'] for item in self.labelled]
        Y = [BaseNerTagger._sent2labels(item['raw']) for item in self.labelled]
        self.model.fit(X, Y)

    def save_example(self, data):
        """
        Saves the current example with the user tagged data
        Args:
            data: User tagged data. [list of tags]

        Returns:

        """
        if len(data) != len(self.current_example['raw']):
            return False
        else:
            toret = []
            for index in range(len(data)):
                toret.append(
                    (self.current_example['raw'][index][0], self.current_example['raw'][index][1], data[index][1]))

            example = self.current_example
            example['raw'] = toret
            example['features'] = BaseNerTagger._sent2features(toret)
            self.labelled.append(example)
            self.unlabelled.pop(self.current_example_index)

    def save_data(self, filepath=None):
        """
        Saves the labelled data to a file
        Args:
            filepath: file to save the data in a pickle format.

        Returns:

        """
        if filepath is None:
            filepath = os.path.join(self.data_directory, 'ner_tagged_data.pickle')
        with open(filepath, 'wb') as out:
            pickle.dump(self.labelled, out)

    def load_data(self, filepath=None):
        """
        Loads labelled data from file.
        Args:
            filepath: file containing pickeled labelled dataset

        Returns:

        """
        with open(filepath, 'rb') as inp:
            self.labelled = pickle.load(inp)
            for lab in self.labelled:
                lab['features'] = BaseNerTagger._sent2features(lab['raw'])

    def add_unlabelled_examples(self, examples):
        """
        Append more unlabelled data to dataset
        Args:
            examples: List of strings

        Returns:

        """
        new_examples = [{'raw': BaseNerTagger._get_pos_tagged_example(text)} for text in examples]
        self.unlabelled.extend(new_examples)


list_of_colors = "#e6194B, #3cb44b, #ffe119, #4363d8, #f58231, #911eb4, #42d4f4, #f032e6, #bfef45, #fabebe, #469990, " \
                 "#e6beff, #9A6324, #fffac8, #800000, #aaffc3, #808000, #ffd8b1, #000075, #a9a9a9 "
list_of_colors = list_of_colors.split(', ')





class NerTagger:
    def __init__(self, dataset, unique_tags, data_directory=''):
        """
        Initialize the NER tagger with a list of strings and unique tags list.
        Args:
            dataset: list of strings.
            unique_tags: list of ('TagID', 'Tag Name') tuples.
            data_directory: default data directory.
        """
        self.unique_tags = unique_tags
        self.ntagger = BaseNerTagger(dataset, data_directory=data_directory)
        self.app = NerTagger._get_app(self.ntagger, self.unique_tags)
        self.utmapping = {t[0]: t[1] for t in self.unique_tags}

    @staticmethod
    def _is_a_tag(span):
        if 'data-tag' in span.attrs:
            return True
        return False

    def _get_bilou_tags_from_html(html):
        soup = BeautifulSoup(html, 'html.parser')
        toret = []

        tag_items = soup.find_all('span', attrs={'data-tag': True})
        #     return tag_items
        tag_ids = [item.attrs['data-tag-id'] for item in tag_items]
        counter = Counter(tag_ids)

        items = soup.find_all('span')
        max_items = len(items)
        index = 0
        while index < max_items:
            item = items[index]
            if NerTagger._is_a_tag(item):
                tag_id = item.attrs['data-tag-id']
                tag = item.attrs['data-tag']
                size = counter[tag_id]
                if size == 1:
                    toret.append((item.text, f'U-{tag}'))
                    index += 1
                elif size == 2:
                    toret.append((item.text, f'B-{tag}'))
                    toret.append((items[index + 1].text, f'L-{tag}'))
                    index += 2
                else:
                    toret.append((item.text, f'B-{tag}'))
                    for i in range(size - 2):
                        toret.append((items[index + i + 1].text, f'I-{tag}'))
                    toret.append((items[index + size - 1].text, f'L-{tag}'))
                    index += size
            else:
                toret.append((item.text, 'O'))
                index += 1

        return toret

    @staticmethod
    def _generate_html_from_example(ex):
        spans = []
        if type(ex) == type({}):
            ex = ex['raw']
        for item in ex:
            tag = Tag(name='span')
            tag.insert(0, item[0])
            spans.append(tag)

        if len(ex[0]) == 3:
            tagidcounter = 0
            last_tag = ''
            for i in range(len(ex)):
                tag = ex[i][2]
                if tag[0] in ['B', 'I']:
                    tag = tag[2:]
                    spans[i].attrs['data-tag-id'] = tagidcounter
                    spans[i].attrs['data-tag'] = tag
                    spans[i].attrs['class'] = tag

                elif tag[0] in ['L', 'U']:
                    tag = tag[2:]
                    spans[i].attrs['data-tag-id'] = tagidcounter
                    spans[i].attrs['data-tag'] = tag
                    spans[i].attrs['class'] = tag
                    tagidcounter += 1

        soup = BeautifulSoup(features='html.parser')
        soup.extend(spans)
        return str(soup)


    @staticmethod
    def _render_app_template(unique_tags_data):
        """
        Tag data list of tuples (tag_id, readable_tag_name)
        Args:
            unique_tags_data: list of tag tuples

        Returns: html template to render

        """

        if len(unique_tags_data) > len(list_of_colors):
            return "Too many tags. Add more colors to list_of_colors"

        trainer_path = os.path.join(os.path.dirname(__file__), 'html_templates', 'ner_trainer.html')
        with open(trainer_path) as templ:
            template = Template(templ.read())

        css_classes = []
        for index, item in enumerate(unique_tags_data):
            css_classes.append((item[0], list_of_colors[index]))

        return template.render(css_classes=css_classes, id_color_map=css_classes, tag_controls=unique_tags_data)


    @staticmethod
    def _get_app(ntagger, tags):
        app = Flask(__name__)

        @app.route("/")
        def base_app():
            return NerTagger._render_app_template(tags)

        @app.route('/load_example')
        def load_example():
            if ntagger.model is None:
                example = ntagger.get_new_random_example()
            else:
                example = ntagger.query_new_example(mode='max')

            html = NerTagger._generate_html_from_example(example)
            return html

        @app.route('/update_model')
        def update_model():
            ntagger.update_model()
            return "Model Updated Successfully"

        @app.route('/save_example', methods=['POST'])
        def save_example():
            form_data = request.form
            html = form_data['html']
            user_tags = NerTagger._get_bilou_tags_from_html(html)
            ntagger.save_example(user_tags)
            return 'Success'

        @app.route('/save_data')
        def save_tagged_data():
            print("save_tagged_data")
            ntagger.save_data()
            return 'Data Saved'

        return app


    def start_server(self, port=None):
        """
        Start the ner tagging server
        Args:
            port: Port number to bind the server to.

        Returns:

        """
        if port:
            self.app.run(port)
        else:
            self.app.run(port=5050)

    def add_unlabelled_examples(self, examples):
        """
        Append unlabelled examples to dataset
        Args:
            examples: list of strings

        Returns:

        """
        self.ntagger.add_unlabelled_examples(examples)

    def save_labelled_examples(self, filepath):
        """
        Save labelled examples to file
        Args:
            filepath: destination filename

        Returns:

        """

        self.ntagger.save_data(filepath)

    def load_labelled_examples(self, filepath):
        """
        Load labelled examples to the dataset
        Args:
            filepath: source filename

        Returns:

        """

        self.ntagger.load_data(filepath)

    def save_model(self, model_filename):
        """
        Save ner model to file
        Args:
            model_filename: model filepath

        Returns:

        """

        with open(model_filename, 'wb') as out:
            pickle.dump(self.ntagger.model, out)

    def load_model(self, model_filename):
        """
        Load ner model from file
        Args:
            model_filename: source filename

        Returns:

        """

        with open(model_filename, 'rb') as inp:
            self.ntagger.model = pickle.load(inp)

    def update_model(self):
        """
        Updates the model
        Returns:

        """

        self.ntagger.update_model()

    def find_entities_in_text(self, text):
        text = BaseNerTagger._get_pos_tagged_example(text)
        features = BaseNerTagger._sent2features(text)
        prediction = self.ntagger.model.predict_single(features)
        lst = zip([t[0] for t in text], prediction)
        curr_ent = 'O'
        ent_toks = []
        entities = []
        for item in lst:
            text = item[0]
            tag = item[1]
            if tag.startswith('B-'):
                if len(ent_toks) > 0:
                    entities.append({
                        'value': ' '.join(ent_toks),
                        'entity': self.utmapping[curr_ent],
                    })
                    ent_toks = []
                curr_ent = tag[2:]
                ent_toks.append(text)
            elif tag.startswith('I-'):
                if curr_ent == 'O':
                    continue
                ent_toks.append(text)
            elif tag.startswith('L-'):
                if curr_ent == 'O':
                    continue
                ent_toks.append(text)
                entities.append({
                    'value': ' '.join(ent_toks),
                    'entity': self.utmapping[curr_ent],
                })
                ent_toks = []
            elif tag.startswith('U-'):
                curr_ent = tag[2:]
                ent_toks = []
                entities.append({
                    'value': text,
                    'entity': self.utmapping[curr_ent],
                })
            elif tag.startswith('O'):
                if len(ent_toks) > 0:
                    entities.append({
                        'value': ' '.join(ent_toks),
                        'entity': self.utmapping[curr_ent],
                    })
                ent_toks = []
                curr_ent = 'O'

        if len(ent_toks) > 0:
            entities.append({
                'value': ' '.join(ent_toks),
                'entity': self.utmapping[curr_ent],
            })
        return entities


if __name__ == '__main__':
    # Unique Tags / Classes
    # tags are given in the below format.
    tags = [
        ("CT", "Course Title"),
        ("CC", "Course Code"),
        ("PREQ", "Pre-requisites"),
        ("PROF", "Professor"),
        ("SE", "Season"),
        ("CR", "Credits")
    ]

    texts = [
        'text one',
        'text two',
        'text three',
        'this is text four'
    ]

    tgr = NerTagger(texts, tags)
    tgr.start_server()
