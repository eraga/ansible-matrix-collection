from __future__ import absolute_import, division, print_function

__metaclass__ = type


def list_to_room_members(list, value):
    result = {}
    for login in list:
        result[login] = value
    return result


class FilterModule(object):
    ''' Ansible core jinja2 filters '''

    def filters(self):
        return {
            'list2members': list_to_room_members,
        }
