from django.db import models
from django.core.validators import EmailValidator
from django.utils import timezone

STATUS_CHOICES = [
    ('ACTIVE', 'Active'),
    ('COMPLETED', 'Completed'),
    ('ON_HOLD', 'On Hold')
]

TASK_STATUS_CHOICES = [
    ('TODO', 'To Do'),
    ('IN_PROGRESS', 'In Progress'),
    ('DONE', 'Done')
]


class Organization(models.Model):
    name = models.CharField(max_length=100)
    slug = models.SlugField(unique=True, help_text="Unique identifier for the organization")
    contact_email = models.EmailField(validators=[EmailValidator()])
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['name']
        verbose_name = 'Organization'
        verbose_name_plural = 'Organizations'

    def __str__(self):
        return self.name

    @property
    def project_count(self):
        return self.projects.count()

    @property
    def active_projects_count(self):
        return self.projects.filter(status='ACTIVE').count()



class Project(models.Model):
    organization = models.ForeignKey(
        Organization, 
        on_delete=models.CASCADE,
        related_name='projects'
    )
    name = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    status = models.CharField(
        max_length=20, 
        choices=STATUS_CHOICES,
        default='ACTIVE'
    )
    due_date = models.DateField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['organization', 'status']),
            models.Index(fields=['status', 'due_date']),
        ]
        verbose_name = 'Project'
        verbose_name_plural = 'Projects'

    def __str__(self):
        return f"{self.name} ({self.organization.name})"

    @property
    def task_count(self):
        return self.tasks.count()

    @property
    def completed_tasks_count(self):
        return self.tasks.filter(status='DONE').count()

    @property
    def completion_percentage(self):
        total_tasks = self.task_count
        if total_tasks == 0:
            return 0
        return round((self.completed_tasks_count / total_tasks) * 100, 1)

    @property
    def is_overdue(self):
        if self.due_date:
            return self.due_date < timezone.now().date() and self.status != 'COMPLETED'
        return False

    def get_tasks_by_status(self):
        return {
            'todo': self.tasks.filter(status='TODO').count(),
            'in_progress': self.tasks.filter(status='IN_PROGRESS').count(),
            'done': self.tasks.filter(status='DONE').count(),
        }


class Task(models.Model):
    project = models.ForeignKey(
        Project, 
        on_delete=models.CASCADE,
        related_name='tasks'
    )
    title = models.CharField(max_length=200)
    description = models.TextField(blank=True)
    status = models.CharField(
        max_length=20, 
        choices=TASK_STATUS_CHOICES,
        default='TODO'
    )
    assignee_email = models.EmailField(
        blank=True,
        validators=[EmailValidator()],
        help_text="Email of the person assigned to this task"
    )
    due_date = models.DateTimeField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-created_at']
        indexes = [
            models.Index(fields=['project', 'status']),
            models.Index(fields=['assignee_email', 'status']),
            models.Index(fields=['status', 'due_date']),
        ]
        verbose_name = 'Task'
        verbose_name_plural = 'Tasks'

    def __str__(self):
        return f"{self.title} - {self.project.name}"

    @property
    def comment_count(self):
        return self.comments.count()

    @property
    def is_overdue(self):
        if self.due_date:
            return self.due_date < timezone.now() and self.status != 'DONE'
        return False

    @property
    def organization(self):
        return self.project.organization


class TaskComment(models.Model):
    task = models.ForeignKey(
        Task, 
        on_delete=models.CASCADE,
        related_name='comments'
    )
    content = models.TextField()
    author_email = models.EmailField(validators=[EmailValidator()])
    timestamp = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ['-timestamp']
        indexes = [
            models.Index(fields=['task', 'timestamp']),
            models.Index(fields=['author_email', 'timestamp']),
        ]
        verbose_name = 'Task Comment'
        verbose_name_plural = 'Task Comments'

    def __str__(self):
        return f"Comment by {self.author_email} on {self.task.title}"

    @property
    def organization(self):
        return self.task.project.organization