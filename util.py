# This software is licensed under the MIT License, which allows you to use,
# copy, modify, merge, publish, distribute, and sell copies of the software,
# with the requirement to include the original copyright notice and this
# permission notice in all copies or substantial portions of the software.
#
# The software is provided 'as is', without any warranty.

import os
from zoneinfo import ZoneInfo

# Helper functions
def read_file(file_name):
    with open(file_name, 'r') as file:
        data = file.read().replace('\n', '')

    return data

def read_version():
    if os.path.isfile('./VERSION'):
        return read_file('./VERSION')

    return read_file('../VERSION')

def number_to_rgb(number, max_value):
    normalized_value = number / max_value
    r = int((1 - normalized_value) * 255)
    g = int(normalized_value * 255)
    b = int((0.5 - abs(normalized_value - 0.5)) * 2 * 255) if normalized_value > 0.5 else 0
    return { 'r': r, 'g': g, 'b': b }

def rgb_to_number(rgb):
    return int(((rgb['r'] & 0xFF) << 16) + ((rgb['g'] & 0xFF) << 8) + (rgb['b'] & 0xFF))

def find_key_by_value(my_dict, target_value):
    for key, value in my_dict.items():
        if value == target_value:
            return key
    return None
