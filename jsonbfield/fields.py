import json
import six
from psycopg2.extras import Json

from django.contrib.postgres import forms, lookups
from django.contrib.postgres.lookups import PostgresSimpleLookup
from django.core import exceptions
from django.db.models import Field, Transform
from django.utils.translation import ugettext_lazy as _
from django.core.serializers.json import DjangoJSONEncoder

from jsonbfield import forms as jsonb_forms

__all__ = ['JSONField']

def dumps(value):
    return DjangoJSONEncoder().encode(value)

class JSONField(Field):
    empty_strings_allowed = False
    description = _('A JSON object')
    default_error_messages = {
        'invalid': _("Value must be valid JSON."),
    }

    def db_type(self, connection):
        return 'jsonb'

    def get_transform(self, name):
        transform = super(JSONField, self).get_transform(name)
        if transform:
            return transform
        return KeyTransformFactory(name)

    def get_prep_value(self, value):
        if value is not None:
            return Json(value)
        return value

    def get_prep_lookup(self, lookup_type, value):
        if lookup_type in ('has_key', 'has_keys', 'has_any_keys'):
            return value
        if isinstance(value, (dict, list)):
            return Json(value)
        return super(JSONField, self).get_prep_lookup(lookup_type, value)

    # Taken from https://github.com/django-extensions/django-extensions/blob/54fe88df801d289882a79824be92d823ab7be33e/django_extensions/db/fields/json.py
    def get_db_prep_save(self, value, connection, **kwargs):
        """Convert our JSON object to a string before we save"""
        if value is None and self.null:
            return None
        # default values come in as strings; only non-strings should be
        # run through `dumps`
        if not isinstance(value, six.string_types):
            value = dumps(value)

        return value

    def validate(self, value, model_instance):
        super(JSONField, self).validate(value, model_instance)
        try:
            json.dumps(value)
        except TypeError:
            raise exceptions.ValidationError(
                self.error_messages['invalid'],
                code='invalid',
                params={'value': value},
            )

    def value_to_string(self, obj):
        value = self._get_val_from_obj(obj)
        return value

    def formfield(self, **kwargs):
        defaults = {'form_class': jsonb_forms.JSONField}
        defaults.update(kwargs)
        return super(JSONField, self).formfield(**defaults)


JSONField.register_lookup(lookups.DataContains)
JSONField.register_lookup(lookups.ContainedBy)

class HasKey(PostgresSimpleLookup):
    lookup_name = 'has_key'
    operator = '?'


class HasKeys(PostgresSimpleLookup):
    lookup_name = 'has_keys'
    operator = '?&'


class HasAnyKeys(PostgresSimpleLookup):
    lookup_name = 'has_any_keys'
    operator = '?|'

JSONField.register_lookup(HasKey)
JSONField.register_lookup(HasKeys)
JSONField.register_lookup(HasAnyKeys)


class KeyTransform(Transform):

    def __init__(self, key_name, *args, **kwargs):
        super(KeyTransform, self).__init__(*args, **kwargs)
        self.key_name = key_name

    def as_sql(self, compiler, connection):
        key_transforms = [self.key_name]
        previous = self.lhs
        while isinstance(previous, KeyTransform):
            key_transforms.insert(0, previous.key_name)
            previous = previous.lhs
        lhs, params = compiler.compile(previous)
        if len(key_transforms) > 1:
            return "{} #> %s".format(lhs), [key_transforms] + params
        try:
            int(self.key_name)
        except ValueError:
            lookup = "'%s'" % self.key_name
        else:
            lookup = "%s" % self.key_name
        return "%s -> %s" % (lhs, lookup), params


class KeyTransformFactory(object):

    def __init__(self, key_name):
        self.key_name = key_name

    def __call__(self, *args, **kwargs):
        return KeyTransform(self.key_name, *args, **kwargs)
