from django.db import models
from core.models import BaseModel, ActiveMixin
from users_roles.models import User
from storage.models import MediaFile

#--------------------------------------------------------------
# Student Status Enum
#--------------------------------------------------------------

class StudentStatus(models.TextChoices):
    ACTIVE = 'ACTIVE', 'Active'
    INACTIVE = 'INACTIVE', 'Inactive'
    SUSPENDED = 'SUSPENDED', 'Suspended'
    ALUMNI = 'ALUMNI', 'Alumni'
    ARCHIVED = 'ARCHIVED', 'Archived'

#--------------------------------------------------------------
# Document Type Enum
#--------------------------------------------------------------

class DocumentType(models.TextChoices):
    IDENTITY = 'IDENTITY', 'Identity'
    ACADEMIC = 'ACADEMIC', 'Academic'
    CERTIFICATE = 'CERTIFICATE', 'Certificate'
    OTHER = 'OTHER', 'Other'

#--------------------------------------------------------------
# Note Visibility Enum
#--------------------------------------------------------------

class NoteVisibility(models.TextChoices):
    INTERNAL = 'INTERNAL', 'Internal'
    ADMIN_ONLY = 'ADMIN_ONLY', 'Admin Only'

#--------------------------------------------------------------
# Student Tag
#--------------------------------------------------------------

class StudentTag(BaseModel):
    academy = models.ForeignKey('academy.Academy', on_delete=models.CASCADE, null=True, blank=True, related_name='student_tags')
    name = models.CharField(max_length=100)
    description = models.TextField(blank=True, default='')

    class Meta:
        db_table = 'student_tags'
        ordering = ['name']

    def __str__(self):
        return f"{self.name}"

#--------------------------------------------------------------
# Student Profile
#--------------------------------------------------------------

class StudentProfile(BaseModel, ActiveMixin):
    user = models.OneToOneField(User, on_delete=models.CASCADE, related_name='student_profile')
    student_code = models.CharField(max_length=50, db_index=True)
    display_name = models.CharField(max_length=255)
    date_of_birth = models.DateField(null=True, blank=True)
    bio = models.TextField(blank=True, default='')

    profile_photo = models.ForeignKey(
        MediaFile,
        on_delete=models.SET_NULL,
        null=True,
        blank=True,
        related_name='student_profile_photos'
    )

    status = models.CharField(
        max_length=20,
        choices=StudentStatus.choices,
        default=StudentStatus.ACTIVE,
        db_index=True
    )
    joined_at = models.DateTimeField(auto_now_add=True)

    tags = models.ManyToManyField(StudentTag, blank=True, related_name='students')

    class Meta:
        db_table = 'student_profiles'
        ordering = ['-joined_at']

    def __str__(self):
        return f"{self.display_name} ({self.student_code})"

#--------------------------------------------------------------
# Student Guardian
#--------------------------------------------------------------

class StudentGuardian(BaseModel):
    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name='guardians', null=True, blank=True)
    name = models.CharField(max_length=255)
    relationship = models.CharField(max_length=100)
    phone = models.CharField(max_length=30)
    email = models.EmailField(blank=True, default='')
    is_primary = models.BooleanField(default=False)

    class Meta:
        db_table = 'student_guardians'
        ordering = ['-is_primary', 'name']

    def __str__(self):
        return f"{self.name} - {self.relationship} of {self.student.display_name}"

#--------------------------------------------------------------
# Student Document
#--------------------------------------------------------------

class StudentDocument(BaseModel):
    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name='documents', null=True, blank=True)
    title = models.CharField(max_length=255)
    document_type = models.CharField(max_length=30, choices=DocumentType.choices, default=DocumentType.OTHER)
    media_file = models.ForeignKey(MediaFile, on_delete=models.PROTECT, related_name='student_documents', null=True, blank=True)
    description = models.TextField(blank=True, default='')
    uploaded_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='uploaded_student_documents')

    class Meta:
        db_table = 'student_documents'
        ordering = ['-created_at']

    def __str__(self):
        return f"{self.title} ({self.student.display_name})"

#--------------------------------------------------------------
# Student Note
#--------------------------------------------------------------

class StudentNote(BaseModel):
    student = models.ForeignKey(StudentProfile, on_delete=models.CASCADE, related_name='notes', null=True, blank=True)
    note = models.TextField()
    created_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, related_name='created_student_notes')
    visibility = models.CharField(max_length=20, choices=NoteVisibility.choices, default=NoteVisibility.INTERNAL)

    class Meta:
        db_table = 'student_notes'
        ordering = ['-created_at']

    def __str__(self):
        return f"Note on {self.student.display_name} by {self.created_by}"
