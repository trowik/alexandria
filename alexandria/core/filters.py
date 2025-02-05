import json

from django.contrib.postgres.fields.jsonb import KeyTextTransform
from django_filters import BaseCSVFilter, BaseInFilter, CharFilter, Filter, FilterSet
from django_filters.constants import EMPTY_VALUES
from rest_framework.exceptions import ValidationError

from alexandria.core import models


class JSONValueFilter(Filter):
    def filter(self, qs, value):
        if value in EMPTY_VALUES:
            return qs

        valid_lookups = self._valid_lookups(qs)

        try:
            value = json.loads(value)
        except json.decoder.JSONDecodeError:
            raise ValidationError("JSONValueFilter value needs to be json encoded.")

        if isinstance(value, dict):
            # be a bit more tolerant
            value = [value]

        for expr in value:
            if expr in EMPTY_VALUES:  # pragma: no cover
                continue
            if not all(("key" in expr, "value" in expr)):
                raise ValidationError(
                    'JSONValueFilter value needs to have a "key" and "value" and an '
                    'optional "lookup" key.'
                )

            lookup_expr = expr.get("lookup", self.lookup_expr)
            if lookup_expr not in valid_lookups:
                raise ValidationError(
                    f'Lookup expression "{lookup_expr}" not allowed for field '
                    f'"{self.field_name}". Valid expressions: '
                    f'{", ".join(valid_lookups.keys())}'
                )
            # "contains" behaves differently on JSONFields as it does on TextFields.
            # That's why we annotate the queryset with the value.
            # Some discussion about it can be found here:
            # https://code.djangoproject.com/ticket/26511
            if isinstance(expr["value"], str):
                qs = qs.annotate(
                    field_val=KeyTextTransform(expr["key"], self.field_name)
                )
                lookup = {f"field_val__{lookup_expr}": expr["value"]}
            else:
                lookup = {
                    f"{self.field_name}__{expr['key']}__{lookup_expr}": expr["value"]
                }
            qs = qs.filter(**lookup)
        return qs

    def _valid_lookups(self, qs):
        # We need some traversal magic in case field name is a related lookup
        traversals = self.field_name.split("__")
        actual_field = traversals.pop()

        model = qs.model
        for field in traversals:
            model = model._meta.get_field(field).related_model

        return model._meta.get_field(actual_field).get_lookups()


class ActiveGroupFilter(CharFilter):
    def filter(self, qs, value):
        if value in EMPTY_VALUES:
            return qs
        if value not in self.parent.request.user.groups:
            raise ValidationError(
                f"Active group '{value}' is not part of user's assigned groups"
            )
        return qs


class TagsFilter(BaseInFilter):
    def filter(self, qs, value):
        if value in EMPTY_VALUES:
            return qs
        # Documents must have all given tags
        for tag in value:
            qs = qs.filter(tags__pk=tag)

        return qs


class CategoryFilterSet(FilterSet):
    meta = JSONValueFilter(field_name="meta")
    active_group = ActiveGroupFilter()

    class Meta:
        model = models.Category
        fields = ["active_group", "meta"]


class DocumentFilterSet(FilterSet):
    meta = JSONValueFilter(field_name="meta")
    active_group = ActiveGroupFilter()
    tags = TagsFilter()

    class Meta:
        model = models.Document
        fields = ["meta", "category", "tags"]


class FileFilterSet(FilterSet):
    meta = JSONValueFilter(field_name="meta")
    document_meta = JSONValueFilter(field_name="document__meta")
    active_group = ActiveGroupFilter()
    files = BaseCSVFilter(field_name="pk", lookup_expr="in")

    class Meta:
        model = models.File
        fields = ["original", "renderings", "type", "meta", "files"]


class TagFilterSet(FilterSet):
    meta = JSONValueFilter(field_name="meta")
    active_group = ActiveGroupFilter()
    with_documents_in_category = CharFilter(field_name="documents__category__slug")
    with_documents_meta = JSONValueFilter(field_name="documents__meta")
    name = CharFilter(lookup_expr="istartswith")

    class Meta:
        model = models.Tag
        fields = [
            "meta",
            "active_group",
            "with_documents_in_category",
            "with_documents_meta",
            "name",
        ]
