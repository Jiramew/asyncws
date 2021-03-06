# -*- coding: utf-8 -*-
from __future__ import absolute_import

import pickle
import hashlib


def has_http_policy(obj):
    if not isinstance(obj, str):
        return False
    else:
        if obj.startswith('http'):
            return True
        else:
            return False


def md5_string(string):
    if not isinstance(string, str):
        try:
            string = string.decode('utf-8')
        except Exception:
            raise TypeError('string must be unicode')

    return hashlib.md5(string.encode('utf-8')).hexdigest()


def serialize_obj(obj):
    return pickle.dumps(obj)


def unserialize_obj(obj):
    return pickle.loads(obj)
