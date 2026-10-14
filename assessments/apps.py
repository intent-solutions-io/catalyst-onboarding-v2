from django.apps import AppConfig


class AssessmentsConfig(AppConfig):
    name = "assessments"
    verbose_name = "Assessments"

    def ready(self):
        # 018 5.5, first layer: PydanticAI refuses any request to a non-test model, in every environment.
        from pydantic_ai import models

        models.ALLOW_MODEL_REQUESTS = False
