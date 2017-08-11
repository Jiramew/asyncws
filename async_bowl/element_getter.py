# -*- coding: utf-8 -*-
import json
import logging

from itertools import chain
from collections import OrderedDict


class ElementGetter(object):
    count = 1

    def __init__(self, parsing, name=None, is_leaf=False):
        self.__parsing = parsing
        if name is None:
            self.__name = 'name{0}'.format(ElementGetter.count)
        else:
            self.__name = name
        self.__is_leaf = is_leaf
        ElementGetter.count += 1

    @property
    def parsing(self):
        return self.__parsing

    @property
    def is_leaf(self):
        return self.__is_leaf

    @property
    def name(self):
        return self.__name

    def parse(self, origin):
        pass

    def __iter__(self):
        return (i for i in (self.parsing, self.is_leaf, self.name))

    def __repr__(self):
        class_name = type(self).__name__
        return '{}({!r}, {!r}, {!r})'.format(class_name, *self)


class XPATH(ElementGetter):
    def __init__(self, parsing, name=None, is_leaf=False):
        super().__init__(parsing, name, is_leaf)

    def parse(self, origin):
        try:
            result = origin.xpath(self.parsing)
            if len(result) == 0:
                logging.info('{0} with {1}'.format("No result", self.parsing))
            return result
        except Exception as e:
            logging.warning('{0} with {1}'.format(e, self.parsing))


def parsing_tree(tree, parse_tree, result_dict=None, flag=0):
    if result_dict is None:
        result_dict = {}

    if not isinstance(tree, list):
        tree = list(tree)

    if (not isinstance(parse_tree, OrderedDict)) and isinstance(parse_tree, dict):
        if "STOP" in parse_tree:
            parse_tree.pop("STOP")
        parse_tree = OrderedDict(parse_tree)
        parse_tree["STOP"] = True

    def parse(tree, key):
        try:
            result = list(chain.from_iterable(map(key.parse, tree)))
            return result
        except Exception as e:
            logging.warning('{0}'.format(e))

    if isinstance(parse_tree, dict):
        for temp_key in parse_tree.keys():
            temp_value = parse_tree[temp_key]
            if isinstance(temp_key, str) and temp_key == "STOP" and temp_value:
                return result_dict
            tmp_tree = parse(tree, temp_key)
            tmp_name = temp_key.name

            flag = 0
            if isinstance(temp_value, XPATH) and temp_value.is_leaf:
                if isinstance(result_dict, list):
                    flag = 1
                else:
                    result_dict[tmp_name] = []
            elif isinstance(temp_value, dict):
                result_dict[tmp_name] = {}
            elif isinstance(temp_value, list):
                result_dict[tmp_name] = []

            if tmp_tree is None:
                continue

            if flag == 0:
                parsing_tree(tmp_tree, temp_value, result_dict[tmp_name], flag)
            else:
                parsing_tree(tmp_tree, temp_value, result_dict, flag)

    if isinstance(parse_tree, list):
        for temp_dict in parse_tree:
            parsing_tree(tree, temp_dict, result_dict)

    if isinstance(parse_tree, XPATH) and parse_tree.is_leaf:
        raw_result = parse(tree, parse_tree)
        result_dict.append({parse_tree.name: raw_result})


def convert_json_to_element_getter(input_json, output=None):
    if output is None:
        output = {}

    if (not isinstance(input_json, OrderedDict)) and isinstance(input_json, dict):
        if "STOP" in input_json:
            input_json.pop("STOP")
        input_json = OrderedDict(input_json)
        input_json["STOP"] = True

    if isinstance(input_json, dict):
        for temp_key in input_json.keys():
            temp_value = input_json[temp_key]
            if temp_key == "STOP" and temp_value:
                return output
            xpath, name, is_leaf = temp_key.split("$")
            tmp_tree = XPATH(xpath, name=name, is_leaf=is_leaf)

            if isinstance(temp_value, dict):
                output[tmp_tree] = {}
            elif isinstance(temp_value, list):
                output[tmp_tree] = []

            convert_json_to_element_getter(temp_value, output[tmp_tree])

    if isinstance(input_json, list):
        for temp_dict in input_json:
            for k, v in temp_dict.items():
                output.append({XPATH(*k.split("$")): XPATH(*v.split("$"))})


def convert_element_getter_to_json(input_element_getter):
    pass


if __name__ == '__main__':
    import requests
    from lxml import etree

    url = "http://www.sse.com.cn/disclosure/credibility/bonds/regulatory/s_index_3.htm"

    response = requests.get(url)
    html = response.content.decode("utf-8")

    tree = etree.HTML(html)

    parse_tree = {
        XPATH('//div/table/tbody/tr[position() = 3]/td[1]', name="name"): XPATH("text()", is_leaf=True, name="name_1"),
        XPATH('//div/table/tbody/tr[position() > 1 and position() < 5]/td[4]/a',
              name="create_time"): XPATH("@href", is_leaf=True, name="create_time_1"),
        XPATH('//div/table/tbody/tr[position() > 1 and position() < 5]', name="user_list"): [
            {XPATH('td[1]'): XPATH('text()', is_leaf=True, name="user_name")},
            {XPATH('td[2]'): XPATH('text()', is_leaf=True, name="age")},
            {XPATH('td[3]'): XPATH('text()', is_leaf=True, name="company")},
        ],
        XPATH('//div/table/tbody/tr[position() > 4]', name="fond_items"): [
            {XPATH('td[4]/a'): XPATH('@href', is_leaf=True, name="category")},
            {XPATH('td[4]/a'): XPATH('text()', is_leaf=True, name="is_inuse")},
            {XPATH('td[5]'): XPATH('text()', is_leaf=True, name="number")},
            {XPATH('td[6]'): XPATH('text()', is_leaf=True, name="arigatou")},
        ]
    }

    parse_tree = {
        XPATH('//div/table/tbody/tr', name="shanghai"): [
            {XPATH('td[1]'): XPATH('text()', is_leaf=True, name="bond_code")},
            {XPATH('td[2]'): XPATH('text()', is_leaf=True, name="bond_sname")},
            {XPATH('td[3]'): XPATH('text()', is_leaf=True, name="type")},
            {XPATH('td[4]/a'): XPATH('@href', is_leaf=True, name="title")},
            {XPATH('td[4]/a'): XPATH('text()', is_leaf=True, name="title_link")},
            {XPATH('td[5]'): XPATH('text()', is_leaf=True, name="about")},
            {XPATH('td[6]'): XPATH('text()', is_leaf=True, name="date")},
        ]
    }

    result = json.dumps(parsing_tree([tree], parse_tree))

    print(result)

    a = {
        '//div/table/tbody/tr$shanghai$0': [
            {"td[1]$$0": "text()$bond_code$1"},
            {"td[2]$$0": "text()$bond_sname$1"},
            {"td[3]$$0": "text()$type$1"},
            {"td[4]/a$$0": "@href$title$1"},
            {"td[4]/a$$0": "text()$title_link$1"},
            {"td[5]$$0": "text()$about$1"},
            {"td[6]$$0": "text()$date$1"}
        ]
    }

    # a = {
    #     '//div/table/tbody/tr$shanghai$0': [
    #         {"td[1]$$0": "text()$bond_code$1"},
    #         {"td[2]$$0": "text()$bond_sname$1"},
    #         {"td[4]/a$$0": "@href$bond_sname$1"}
    #     ],
    #     '//div/table/tbody/tr[position() > 4]$beijing$0': [
    #         {"td[1]$$0": "text()$bond_code$1"},
    #         {"td[2]$$0": "text()$bond_sname$1"},
    #         {"td[4]/a$$0": "@href$bond_sname$1"}
    #     ],
    #     "//div/table/tbody/tr[position() > 4]$tianjin$0": [
    #         {"td[1]$$0": "text()$aaa$1"}
    #     ]
    # }

    json_a = json.dumps(a)
    dict_a = json.loads(json_a)
    parse_tree_from_convert = convert_json_to_element_getter(dict_a)
    result = json.dumps(parsing_tree([tree], parse_tree_from_convert))

    print(result)
