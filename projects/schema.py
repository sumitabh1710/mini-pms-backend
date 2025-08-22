import graphene
from graphene_django import DjangoObjectType
from .models import Organization, Project, Task, TaskComment, STATUS_CHOICES, TASK_STATUS_CHOICES
from django.core.exceptions import ObjectDoesNotExist, ValidationError
from django.db import transaction
from django.core.validators import validate_email
from django.db.models import Q, Count, Case, When, IntegerField
from django.utils.text import slugify


# ----------------------
# Custom Types
# ----------------------
class ProjectStatisticsType(graphene.ObjectType):
    total_projects = graphene.Int()
    active_projects = graphene.Int()
    completed_projects = graphene.Int()
    on_hold_projects = graphene.Int()
    total_tasks = graphene.Int()
    completed_tasks = graphene.Int()
    completion_rate = graphene.Float()


class TaskStatisticsType(graphene.ObjectType):
    todo_count = graphene.Int()
    in_progress_count = graphene.Int()
    done_count = graphene.Int()
    total_count = graphene.Int()
    completion_percentage = graphene.Float()


class StatusChoiceType(graphene.ObjectType):
    value = graphene.String()
    display = graphene.String()


# ----------------------
# Enhanced GraphQL Types
# ----------------------
class OrganizationType(DjangoObjectType):
    project_count = graphene.Int()
    active_projects_count = graphene.Int()

    class Meta:
        model = Organization
        fields = "__all__"

    def resolve_project_count(self, info):
        # Use related_name if defined in your Project model
        return self.projects.count() if hasattr(self, "projects") else self.project_set.count()

    def resolve_active_projects_count(self, info):
        if hasattr(self, "projects"):
            return self.projects.filter(status="ACTIVE").count()
        return self.project_set.filter(status="ACTIVE").count()


class ProjectType(DjangoObjectType):
    task_count = graphene.Int()
    completed_tasks_count = graphene.Int()
    completion_percentage = graphene.Float()
    is_overdue = graphene.Boolean()
    task_statistics = graphene.Field(TaskStatisticsType)

    class Meta:
        model = Project
        fields = "__all__"

    def resolve_task_count(self, info):
        return self.task_count

    def resolve_completed_tasks_count(self, info):
        return self.completed_tasks_count

    def resolve_completion_percentage(self, info):
        return self.completion_percentage

    def resolve_is_overdue(self, info):
        return self.is_overdue

    def resolve_task_statistics(self, info):
        stats = self.get_tasks_by_status()
        total = sum(stats.values())
        completion_percentage = (stats['done'] / total * 100) if total > 0 else 0
        
        return TaskStatisticsType(
            todo_count=stats['todo'],
            in_progress_count=stats['in_progress'],
            done_count=stats['done'],
            total_count=total,
            completion_percentage=round(completion_percentage, 1)
        )


class TaskType(DjangoObjectType):
    comment_count = graphene.Int()
    is_overdue = graphene.Boolean()
    organization = graphene.Field(OrganizationType)

    class Meta:
        model = Task
        fields = "__all__"

    def resolve_comment_count(self, info):
        return self.comment_count

    def resolve_is_overdue(self, info):
        return self.is_overdue

    def resolve_organization(self, info):
        return self.organization


class TaskCommentType(DjangoObjectType):
    organization = graphene.Field(OrganizationType)

    class Meta:
        model = TaskComment
        fields = "__all__"

    def resolve_organization(self, info):
        return self.organization


# ----------------------
# Enhanced Queries
# ----------------------
class Query(graphene.ObjectType):
    # Basic queries
    organizations = graphene.List(OrganizationType)
    organization = graphene.Field(OrganizationType, slug=graphene.String(required=True))
    projects = graphene.List(
        ProjectType, 
        organization_slug=graphene.String(required=False),
        status=graphene.String(),
        search=graphene.String()
    )
    project = graphene.Field(ProjectType, id=graphene.Int(required=True))
    tasks = graphene.List(
        TaskType, 
        project_id=graphene.Int(required=True),
        status=graphene.String(),
        assignee_email=graphene.String()
    )
    task = graphene.Field(TaskType, id=graphene.Int(required=True))
    task_comments = graphene.List(TaskCommentType, task_id=graphene.Int(required=True))
    
    # Statistics queries
    project_statistics = graphene.Field(
        ProjectStatisticsType,
        organization_slug=graphene.String(required=True)
    )
    
    # Utility queries
    project_status_choices = graphene.List(StatusChoiceType)
    task_status_choices = graphene.List(StatusChoiceType)

    def resolve_organizations(self, info):
        return Organization.objects.all().prefetch_related('projects')

    def resolve_organization(self, info, slug):
        try:
            return Organization.objects.get(slug=slug)
        except Organization.DoesNotExist:
            return None

    def resolve_projects(self, info, organization_slug=None, status=None, search=None):
        queryset = Project.objects.all().select_related('organization').prefetch_related('tasks')
        
        if organization_slug:
            queryset = queryset.filter(organization__slug=organization_slug)

        if status:
            queryset = queryset.filter(status=status)

        if search:
            queryset = queryset.filter(
                Q(name__icontains=search) | Q(description__icontains=search)
            )

        return queryset


    def resolve_project(self, info, id):
        try:
            return Project.objects.select_related('organization').prefetch_related('tasks').get(id=id)
        except Project.DoesNotExist:
            return None

    def resolve_tasks(self, info, project_id, status=None, assignee_email=None):
        queryset = Task.objects.filter(project_id=project_id).select_related('project__organization')
        
        if status:
            queryset = queryset.filter(status=status)
        
        if assignee_email:
            queryset = queryset.filter(assignee_email=assignee_email)
        
        return queryset.prefetch_related('comments')

    def resolve_task(self, info, id):
        try:
            return Task.objects.select_related('project__organization').prefetch_related('comments').get(id=id)
        except Task.DoesNotExist:
            return None

    def resolve_task_comments(self, info, task_id):
        return TaskComment.objects.filter(task_id=task_id).select_related('task__project__organization')

    def resolve_project_statistics(self, info, organization_slug):
        try:
            org = Organization.objects.get(slug=organization_slug)
        except Organization.DoesNotExist:
            raise Exception("Organization not found")

        projects = Project.objects.filter(organization=org)
        
        # Project statistics
        project_stats = projects.aggregate(
            total=Count('id'),
            active=Count(Case(When(status='ACTIVE', then=1), output_field=IntegerField())),
            completed=Count(Case(When(status='COMPLETED', then=1), output_field=IntegerField())),
            on_hold=Count(Case(When(status='ON_HOLD', then=1), output_field=IntegerField()))
        )
        
        # Task statistics
        tasks = Task.objects.filter(project__organization=org)
        task_stats = tasks.aggregate(
            total_tasks=Count('id'),
            completed_tasks=Count(Case(When(status='DONE', then=1), output_field=IntegerField()))
        )
        
        completion_rate = 0
        if task_stats['total_tasks'] > 0:
            completion_rate = round((task_stats['completed_tasks'] / task_stats['total_tasks']) * 100, 1)

        return ProjectStatisticsType(
            total_projects=project_stats['total'],
            active_projects=project_stats['active'],
            completed_projects=project_stats['completed'],
            on_hold_projects=project_stats['on_hold'],
            total_tasks=task_stats['total_tasks'],
            completed_tasks=task_stats['completed_tasks'],
            completion_rate=completion_rate
        )

    def resolve_project_status_choices(self, info):
        return [StatusChoiceType(value=choice[0], display=choice[1]) for choice in STATUS_CHOICES]

    def resolve_task_status_choices(self, info):
        return [StatusChoiceType(value=choice[0], display=choice[1]) for choice in TASK_STATUS_CHOICES]


# ----------------------
# Input Types for Mutations
# ----------------------
class CreateOrganizationInput(graphene.InputObjectType):
    name = graphene.String(required=True)
    # slug = graphene.String(required=True)
    contact_email = graphene.String(required=True)


class CreateProjectInput(graphene.InputObjectType):
    organization_id = graphene.Int(required=True)
    name = graphene.String(required=True)
    description = graphene.String()
    status = graphene.String()
    due_date = graphene.types.datetime.Date()


class CreateTaskInput(graphene.InputObjectType):
    project_id = graphene.Int(required=True)
    title = graphene.String(required=True)
    description = graphene.String()
    status = graphene.String()
    assignee_email = graphene.String()
    due_date = graphene.types.datetime.DateTime()


# ----------------------
# Enhanced Mutations: Create
# ----------------------
class CreateOrganization(graphene.Mutation):
    organization = graphene.Field(OrganizationType)
    success = graphene.Boolean()
    errors = graphene.List(graphene.String)

    class Arguments:
        input = CreateOrganizationInput(required=True)

    def mutate(self, info, input):
        errors = []
        
        # Validation
        try:
            validate_email(input.contact_email)
        except ValidationError:
            errors.append("Invalid email format")

        slug = slugify(input.name.lower())

        if Organization.objects.filter(slug=slug).exists():
            errors.append("Organization with this slug already exists")
        
        if errors:
            return CreateOrganization(success=False, errors=errors)

        try:
            with transaction.atomic():
                org = Organization.objects.create(
                    name=input.name,
                    slug=slug,
                    contact_email=input.contact_email
                )
                return CreateOrganization(organization=org, success=True, errors=[])
        except Exception as e:
            return CreateOrganization(success=False, errors=[str(e)])


class CreateProject(graphene.Mutation):
    project = graphene.Field(ProjectType)
    success = graphene.Boolean()
    errors = graphene.List(graphene.String)

    class Arguments:
        input = CreateProjectInput(required=True)

    def mutate(self, info, input):
        errors = []
        
        try:
            org = Organization.objects.get(id=input.organization_id)
        except Organization.DoesNotExist:
            errors.append("Organization not found")
            return CreateProject(success=False, errors=errors)

        # Validate status
        if input.status and input.status not in [choice[0] for choice in STATUS_CHOICES]:
            errors.append("Invalid status choice")

        if errors:
            return CreateProject(success=False, errors=errors)

        try:
            with transaction.atomic():
                project = Project.objects.create(
                    organization=org,
                    name=input.name,
                    description=input.description or "",
                    status=input.status or "ACTIVE",
                    due_date=input.due_date
                )
                return CreateProject(project=project, success=True, errors=[])
        except Exception as e:
            return CreateProject(success=False, errors=[str(e)])


class CreateTask(graphene.Mutation):
    task = graphene.Field(TaskType)
    success = graphene.Boolean()
    errors = graphene.List(graphene.String)

    class Arguments:
        input = CreateTaskInput(required=True)

    def mutate(self, info, input):
        errors = []
        
        try:
            project = Project.objects.get(id=input.project_id)
        except Project.DoesNotExist:
            errors.append("Project not found")
            return CreateTask(success=False, errors=errors)

        # Validate status
        if input.status and input.status not in [choice[0] for choice in TASK_STATUS_CHOICES]:
            errors.append("Invalid status choice")

        # Validate email
        if input.assignee_email:
            try:
                validate_email(input.assignee_email)
            except ValidationError:
                errors.append("Invalid assignee email format")

        if errors:
            return CreateTask(success=False, errors=errors)

        try:
            with transaction.atomic():
                task = Task.objects.create(
                    project=project,
                    title=input.title,
                    description=input.description or "",
                    status=input.status or "TODO",
                    assignee_email=input.assignee_email or "",
                    due_date=input.due_date
                )
                return CreateTask(task=task, success=True, errors=[])
        except Exception as e:
            return CreateTask(success=False, errors=[str(e)])


class CreateTaskComment(graphene.Mutation):
    comment = graphene.Field(TaskCommentType)
    success = graphene.Boolean()
    errors = graphene.List(graphene.String)

    class Arguments:
        task_id = graphene.Int(required=True)
        content = graphene.String(required=True)
        author_email = graphene.String(required=True)

    def mutate(self, info, task_id, content, author_email):
        errors = []
        
        try:
            task = Task.objects.get(id=task_id)
        except Task.DoesNotExist:
            errors.append("Task not found")
            return CreateTaskComment(success=False, errors=errors)

        # Validate email
        try:
            validate_email(author_email)
        except ValidationError:
            errors.append("Invalid author email format")

        if not content.strip():
            errors.append("Comment content cannot be empty")

        if errors:
            return CreateTaskComment(success=False, errors=errors)

        try:
            with transaction.atomic():
                comment = TaskComment.objects.create(
                    task=task,
                    content=content.strip(),
                    author_email=author_email
                )
                return CreateTaskComment(comment=comment, success=True, errors=[])
        except Exception as e:
            return CreateTaskComment(success=False, errors=[str(e)])


# ----------------------
# Enhanced Mutations: Update
# ----------------------
class UpdateProject(graphene.Mutation):
    project = graphene.Field(ProjectType)
    success = graphene.Boolean()
    errors = graphene.List(graphene.String)

    class Arguments:
        project_id = graphene.Int(required=True)
        name = graphene.String()
        description = graphene.String()
        status = graphene.String()
        due_date = graphene.types.datetime.Date()

    def mutate(self, info, project_id, name=None, description=None, status=None, due_date=None):
        errors = []
        
        try:
            project = Project.objects.get(id=project_id)
        except Project.DoesNotExist:
            errors.append("Project not found")
            return UpdateProject(success=False, errors=errors)

        # Validate status
        if status and status not in [choice[0] for choice in STATUS_CHOICES]:
            errors.append("Invalid status choice")

        if errors:
            return UpdateProject(success=False, errors=errors)

        try:
            with transaction.atomic():
                if name is not None:
                    project.name = name
                if description is not None:
                    project.description = description
                if status is not None:
                    project.status = status
                if due_date is not None:
                    project.due_date = due_date

                project.save()
                return UpdateProject(project=project, success=True, errors=[])
        except Exception as e:
            return UpdateProject(success=False, errors=[str(e)])


class UpdateTask(graphene.Mutation):
    task = graphene.Field(TaskType)
    success = graphene.Boolean()
    errors = graphene.List(graphene.String)

    class Arguments:
        task_id = graphene.Int(required=True)
        title = graphene.String()
        description = graphene.String()
        status = graphene.String()
        assignee_email = graphene.String()
        due_date = graphene.types.datetime.DateTime()

    def mutate(self, info, task_id, title=None, description=None, status=None, assignee_email=None, due_date=None):
        errors = []
        
        try:
            task = Task.objects.get(id=task_id)
        except Task.DoesNotExist:
            errors.append("Task not found")
            return UpdateTask(success=False, errors=errors)

        # Validate status
        if status and status not in [choice[0] for choice in TASK_STATUS_CHOICES]:
            errors.append("Invalid status choice")

        # Validate email
        if assignee_email:
            try:
                validate_email(assignee_email)
            except ValidationError:
                errors.append("Invalid assignee email format")

        if errors:
            return UpdateTask(success=False, errors=errors)

        try:
            with transaction.atomic():
                if title is not None:
                    task.title = title
                if description is not None:
                    task.description = description
                if status is not None:
                    task.status = status
                if assignee_email is not None:
                    task.assignee_email = assignee_email
                if due_date is not None:
                    task.due_date = due_date

                task.save()
                return UpdateTask(task=task, success=True, errors=[])
        except Exception as e:
            return UpdateTask(success=False, errors=[str(e)])


# ----------------------
# Delete Mutations
# ----------------------
class DeleteProject(graphene.Mutation):
    success = graphene.Boolean()
    errors = graphene.List(graphene.String)

    class Arguments:
        project_id = graphene.Int(required=True)

    def mutate(self, info, project_id):
        try:
            project = Project.objects.get(id=project_id)
            project.delete()
            return DeleteProject(success=True, errors=[])
        except Project.DoesNotExist:
            return DeleteProject(success=False, errors=["Project not found"])
        except Exception as e:
            return DeleteProject(success=False, errors=[str(e)])


class DeleteTask(graphene.Mutation):
    success = graphene.Boolean()
    errors = graphene.List(graphene.String)

    class Arguments:
        task_id = graphene.Int(required=True)

    def mutate(self, info, task_id):
        try:
            task = Task.objects.get(id=task_id)
            task.delete()
            return DeleteTask(success=True, errors=[])
        except Task.DoesNotExist:
            return DeleteTask(success=False, errors=["Task not found"])
        except Exception as e:
            return DeleteTask(success=False, errors=[str(e)])


class DeleteTaskComment(graphene.Mutation):
    success = graphene.Boolean()
    errors = graphene.List(graphene.String)

    class Arguments:
        comment_id = graphene.Int(required=True)

    def mutate(self, info, comment_id):
        try:
            comment = TaskComment.objects.get(id=comment_id)
            comment.delete()
            return DeleteTaskComment(success=True, errors=[])
        except TaskComment.DoesNotExist:
            return DeleteTaskComment(success=False, errors=["Comment not found"])
        except Exception as e:
            return DeleteTaskComment(success=False, errors=[str(e)])


# ----------------------
# Root Mutation
# ----------------------
class Mutation(graphene.ObjectType):
    # Create mutations
    create_organization = CreateOrganization.Field()
    create_project = CreateProject.Field()
    create_task = CreateTask.Field()
    create_task_comment = CreateTaskComment.Field()
    
    # Update mutations
    update_project = UpdateProject.Field()
    update_task = UpdateTask.Field()
    
    # Delete mutations
    delete_project = DeleteProject.Field()
    delete_task = DeleteTask.Field()
    delete_task_comment = DeleteTaskComment.Field()


# ----------------------
# Schema
# ----------------------
schema = graphene.Schema(query=Query, mutation=Mutation)