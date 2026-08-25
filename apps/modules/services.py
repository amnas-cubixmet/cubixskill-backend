from django.db import transaction, models
from modules.models import Module
from courses.models import Course
from core.utils import CubixSkillAPIException

#--------------------------------------------------------------
# Module Services
#--------------------------------------------------------------

class ModuleService:
    @staticmethod
    @transaction.atomic
    def create_module(course: Course, title: str, description: str = '', is_demo: bool = False) -> Module:
        max_order = Module.objects.filter(course=course).aggregate(models.Max('order_index'))['order_index__max'] or 0
        module = Module.objects.create(
            course=course,
            title=title,
            description=description,
            is_demo=is_demo,
            order_index=max_order + 1
        )
        return module

    @staticmethod
    @transaction.atomic
    def reorder_course_modules(course: Course, modules_order: list) -> None:
        """
        modules_order format: [ {"id": "uuid-1", "order_index": 1}, {"id": "uuid-2", "order_index": 2} ]
        """
        valid_ids = set(Module.objects.filter(course=course).values_list('id', flat=True))
        for item in modules_order:
            module_id = item.get('id')
            new_order = item.get('order_index')
            if module_id and new_order is not None and str(module_id) in [str(vid) for vid in valid_ids]:
                Module.objects.filter(id=module_id, course=course).update(order_index=new_order)

    @staticmethod
    @transaction.atomic
    def delete_module(module: Module) -> None:
        """
        Deletes a course module and its child lessons in a clean atomic transaction.
        """
        module.delete()
