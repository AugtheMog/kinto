import time
import json
import ast
import re

import six
import colander
from cornice.resource import view

from readinglist.backend.exceptions import RecordNotFoundError


def exists_or_404():
    """View decorator to catch unknown record errors in backend."""
    def wrap(view):
        def wrapped_view(self, *args, **kwargs):
            try:
                return view(self, *args, **kwargs)
            except RecordNotFoundError as e:
                self.request.errors.add('path', 'id', six.text_type(e))
                self.request.errors.status = "404 Resource Not Found"
        return wrapped_view
    return wrap


def validates_or_400():
    """View decorator to catch validation errors and return 400 responses."""
    def wrap(view):
        def wrapped_view(self, *args, **kwargs):
            try:
                return view(self, *args, **kwargs)
            except ValueError as e:
                self.request.errors.add('body', 'body', six.text_type(e))
            except colander.Invalid as e:
                # Transform the errors we got from colander into cornice errors
                for field, error in e.asdict().items():
                    self.request.errors.add('body', field, error)
            self.request.errors.status = "400 Bad Request"
        return wrapped_view
    return wrap


class TimeStamp(colander.SchemaNode):
    """Basic integer field that takes current timestamp if no value
    is provided.
    """
    schema_type = colander.Integer
    title = 'Epoch timestamp'

    @staticmethod
    def now():
        return int(time.time())

    def deserialize(self, cstruct):
        if cstruct is colander.null and self.required:
            cstruct = TimeStamp.now()
        return super(TimeStamp, self).deserialize(cstruct)


class RessourceSchema(colander.MappingSchema):
    """Base resource schema.

    It brings common fields and behaviour for all inherited schemas.
    """
    _id = colander.SchemaNode(colander.String(), missing=colander.drop)
    last_modified = TimeStamp()


class BaseResource(object):

    mapping = RessourceSchema()
    id_field = '_id'
    modified_field = 'last_modified'

    def __init__(self, request):
        self.request = request
        self.db = request.db
        self.db_kwargs = dict(resource=self,
                              user_id=request.authenticated_userid)
        self.record = None
        self.known_fields = [c.name for c in self.mapping.children]

    def deserialize(self, raw):
        raw = raw.decode('utf-8')
        return json.loads(raw) if raw else {}

    def validate(self, record):
        return self.mapping.deserialize(record)

    def _extract_filters(self, queryparams):
        """Extracts filters from QueryString parameters."""
        filters = []

        for param, value in queryparams.items():
            value = self.__decode_filter_value(value)
            if param in self.known_fields:
                filters.append((param, value, '=='))
            if param == 'since':
                filters.append((self.modified_field, value, '>='))

        return filters

    def _extract_sorting(self, queryparams):
        """Extracts filters from QueryString parameters."""
        specified = queryparams.get('sort', '').split(',')
        sorting = []
        for field in specified:
            m = re.match(r'\s?([\-+]?)(\w+)\s?', field)
            if m:
                order, field = m.groups()
                direction = -1 if order == '-' else 1
                sorting.append((field, direction))
        return sorting

    def __decode_filter_value(self, value):
        """Converts string value to native python values."""
        if value.lower() in ['on', 'true', 'yes', '1']:
            value = True
        elif value.lower() in ['off', 'false', 'no', '0']:
            value = False
        try:
            return ast.literal_eval(value)
        except ValueError:
            return value

    #
    # End-points
    #

    @view(permission='readonly')
    def collection_get(self):
        filters = self._extract_filters(self.request.GET)
        sorting = self._extract_sorting(self.request.GET)
        records = self.db.get_all(filters=filters,
                                  sorting=sorting,
                                  **self.db_kwargs)
        meta = {
            'total': len(records)
        }
        body = {
            'items': records,
            'meta': meta
        }
        return body

    @view(permission='readwrite')
    @validates_or_400()
    def collection_post(self):
        new_record = self.deserialize(self.request.body)
        new_record = self.validate(new_record)
        self.record = self.db.create(record=new_record, **self.db_kwargs)
        return self.record

    @view(permission='readonly')
    @exists_or_404()
    def get(self):
        record_id = self.request.matchdict['id']
        self.record = self.db.get(record_id=record_id, **self.db_kwargs)
        return self.record

    @view(permission='readwrite')
    @exists_or_404()
    @validates_or_400()
    def put(self):
        record_id = self.request.matchdict['id']
        new_record = self.deserialize(self.request.body)
        new_record = self.validate(new_record)
        self.record = self.db.update(record_id=record_id,
                                     record=new_record,
                                     **self.db_kwargs)
        return self.record

    @view(permission='readwrite')
    @exists_or_404()
    @validates_or_400()
    def patch(self):
        record_id = self.request.matchdict['id']
        self.record = self.db.get(record_id=record_id, **self.db_kwargs)

        modified = self.deserialize(self.request.body)
        updated = self.record.copy()
        updated.update(**modified)
        updated[self.modified_field] = TimeStamp.now()
        updated = self.validate(updated)

        record = self.db.update(record_id=record_id,
                                record=updated,
                                **self.db_kwargs)
        return record

    @view(permission='readwrite')
    @exists_or_404()
    def delete(self):
        record_id = self.request.matchdict['id']
        self.record = self.db.delete(record_id=record_id, **self.db_kwargs)
        return self.record
