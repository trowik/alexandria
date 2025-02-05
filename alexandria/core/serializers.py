from django.contrib.auth.models import AnonymousUser
from django.template.defaultfilters import slugify
from django.utils import translation
from rest_framework.exceptions import ValidationError
from rest_framework_json_api import serializers

from . import models


class BaseSerializer(serializers.ModelSerializer):
    created_at = serializers.DateTimeField(read_only=True)

    validation_classes = []

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._custom_validators = []

        validators = [cls(self) for cls in self.validation_classes]
        for validator in validators:
            for method_name in [m for m in dir(validator) if not m.startswith("_")]:
                method = getattr(validator, method_name)
                if getattr(method, "_validate_model", None) == self.Meta.model:
                    self._custom_validators.append(method)

    def is_valid(self, *args, **kwargs):
        # Prime data so the validators are called (and default values filled
        # if client didn't pass them.)
        self.initial_data.setdefault("created_by_group", self._default_group())
        self.initial_data.setdefault("modified_by_group", self._default_group())
        return super().is_valid(*args, **kwargs)

    def validate(self, *args, **kwargs):
        validated_data = super().validate(*args, **kwargs)

        for func in self._custom_validators:
            validated_data = func(validated_data)

        user = self.context["request"].user
        validated_data["created_by_user"] = user.username
        validated_data["modified_by_user"] = user.username

        self.Meta.model.check_permissions(self.context["request"])
        if self.instance is not None:
            self.instance.check_object_permissions(self.context["request"])

        return validated_data

    def validate_created_by_group(self, value):
        # Created by group can be set on creation, then must remain constant
        if self.instance:
            # can't change created_by_group on existing instances
            return self.instance.created_by_group
        else:
            return self._validate_group(value, "created_by_group")

    def validate_modified_by_group(self, value):
        # Modified by group is validated against the user's list of groups,
        # with a fallback to the default group if no value is given
        return self._validate_group(value or self._default_group(), "modified_by_group")

    def _validate_group(self, value, field_name):
        user = self.context["request"].user
        if value and value not in user.groups:
            raise ValidationError(
                f"Given {field_name} '{value}' is not part of user's assigned groups"
            )
        return value

    def _default_group(self):
        user = self.context["request"].user
        return user.group if not isinstance(user, AnonymousUser) else None

    class Meta:
        fields = (
            "created_at",
            "created_by_user",
            "created_by_group",
            "modified_at",
            "modified_by_user",
            "modified_by_group",
            "meta",
        )


class SlugModelSerializer(BaseSerializer):
    """
    Ensure on creation that the model will receive a slug.

    If no slug is passed via API, one is derived from the `name` field of
    the model, via Django's `slugify()` helper. If the model in question
    does not have a `name` field, you can specify a `slug_source_field`
    attribute on your serializer's `Meta` class to tell it which
    field to use instead.
    """

    def create(self, validated_data):
        slug_field = getattr(self.Meta, "slug_source_field", "name")
        if "slug" not in validated_data:
            slug_source_value = validated_data.get(slug_field)
            if isinstance(slug_source_value, dict):  # pragma: todo cover
                lang = translation.get_language()
                slug_source_value = slug_source_value.get(lang)
            validated_data["slug"] = slugify(slug_source_value)

        return super().create(validated_data)


class CategorySerializer(SlugModelSerializer):
    class Meta:
        model = models.Category
        fields = SlugModelSerializer.Meta.fields + ("name", "description", "color")


class TagSerializer(SlugModelSerializer):
    class Meta:
        model = models.Tag
        fields = SlugModelSerializer.Meta.fields + ("name", "description")
        slug_source_field = "name"


class FileSerializer(BaseSerializer):
    renderings = serializers.ResourceRelatedField(
        required=False, many=True, read_only=True,
    )

    included_serializers = {
        "document": "alexandria.core.serializers.DocumentSerializer",
        "original": "alexandria.core.serializers.FileSerializer",
        "renderings": "alexandria.core.serializers.FileSerializer",
    }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # We only want to provide an upload_url on creation of a file.
        self.new = False
        if "request" in self.context and self.context["request"].method == "POST":
            self.new = True

    download_url = serializers.CharField(read_only=True)
    upload_url = serializers.SerializerMethodField()

    def get_upload_url(self, obj):
        return obj.upload_url if self.new else ""

    def validate(self, *args, **kwargs):
        validated_data = super().validate(*args, **kwargs)
        if validated_data.get(
            "type"
        ) != models.File.ORIGINAL and not validated_data.get("original"):
            f_type = validated_data.get("type")
            raise ValidationError(f'"original" must be set for type "{f_type}".')

        if validated_data.get("type") == models.File.ORIGINAL and validated_data.get(
            "original"
        ):
            f_type = validated_data.get("type")
            raise ValidationError(f'"original" must not be set for type "{f_type}".')

        return validated_data

    class Meta:
        model = models.File
        fields = BaseSerializer.Meta.fields + (
            "type",
            "name",
            "original",
            "renderings",
            "document",
            "download_url",
            "upload_url",
        )


class DocumentSerializer(BaseSerializer):
    files = serializers.ResourceRelatedField(
        queryset=models.File.objects.all(), required=False, many=True
    )
    included_serializers = {
        "category": CategorySerializer,
        "tags": TagSerializer,
        "files": FileSerializer,
    }

    class Meta:
        model = models.Document
        fields = BaseSerializer.Meta.fields + (
            "files",
            "title",
            "description",
            "category",
            "tags",
        )
