"""
Off-device tests for the cue engine validators (_validate_levels, _validate_osc).

Standalone like test_cueengine.py -- xio is not part of the repo pytest suite:
    py xio/new-plugins/showcontrol/test_cueengine_validators.py
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from cueengine import _validate_levels, _validate_osc, CueError  # noqa: E402


def test_valid_normal():
    result = _validate_levels({1: {1: 255, 2: 128}})
    assert result == {1: {1: 255, 2: 128}}
    print("OK valid normal levels")


def test_levels_not_dict():
    try:
        _validate_levels("not a dict")
        assert False, "expected CueError"
    except CueError:
        pass
    print("OK levels not dict raises")


def test_universe_out_of_range():
    try:
        _validate_levels({64000: {1: 128}})
        assert False, "expected CueError"
    except CueError:
        pass
    print("OK universe out of range raises")


def test_channel_out_of_range():
    for bad_channel in (0, 513):
        try:
            _validate_levels({1: {bad_channel: 128}})
            assert False, "expected CueError for channel %d" % bad_channel
        except CueError:
            pass
    print("OK channel out of range raises")


def test_value_out_of_range():
    try:
        _validate_levels({1: {1: 256}})
        assert False, "expected CueError"
    except CueError:
        pass
    print("OK dmx value out of range raises")


def test_string_keys_converted_to_int():
    result = _validate_levels({"1": {"1": "255", "2": "128"}})
    assert result == {1: {1: 255, 2: 128}}
    print("OK string keys converted to int")


def test_osc_none_returns_empty_list():
    assert _validate_osc(None) == []
    print("OK osc none returns empty list")


def test_osc_not_a_list_raises():
    try:
        _validate_osc("not a list")
        assert False, "expected CueError"
    except CueError:
        pass
    print("OK osc not a list raises")


def test_osc_address_missing_slash_raises():
    try:
        _validate_osc([{"address": "no/slash"}])
        assert False, "expected CueError"
    except CueError:
        pass
    print("OK osc address missing slash raises")


def test_osc_args_invalid_type_raises():
    try:
        _validate_osc([{"address": "/test", "args": [{"invalid": "dict"}]}])
        assert False, "expected CueError"
    except CueError:
        pass
    print("OK osc invalid arg type raises")


def test_osc_valid_with_multiple_arg_types():
    osc = [{"address": "/test", "args": [True, 42, 3.14, "hello"]}]
    result = _validate_osc(osc)
    assert result == [{"address": "/test", "args": [True, 42, 3.14, "hello"]}]
    print("OK osc valid with multiple arg types")


def test_osc_valid_without_args():
    result = _validate_osc([{"address": "/test"}])
    assert result == [{"address": "/test", "args": []}]
    print("OK osc valid without args defaults to empty list")


if __name__ == "__main__":
    fns = [v for k, v in sorted(globals().items()) if k.startswith("test_")]
    for fn in fns:
        fn()
    print("\nALL %d PASSED" % len(fns))
