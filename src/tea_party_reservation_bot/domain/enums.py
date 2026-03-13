from enum import StrEnum


class AdminRole(StrEnum):
    OWNER = "owner"
    MANAGER = "manager"


class Permission(StrEnum):
    VIEW_EVENTS = "view_events"
    CREATE_DRAFT = "create_draft"
    PUBLISH_EVENT = "publish_event"
    MANAGE_REGISTRATIONS = "manage_registrations"
    MANAGE_ADMIN_ROLES = "manage_admin_roles"
    MANAGE_SETTINGS = "manage_settings"


class EventStatus(StrEnum):
    DRAFT = "draft"
    READY_FOR_REVIEW = "ready_for_review"
    PUBLISHED_OPEN = "published_open"
    PUBLISHED_FULL = "published_full"
    REGISTRATION_CLOSED = "registration_closed"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ReservationStatus(StrEnum):
    CONFIRMED = "confirmed"
    CANCELLED = "cancelled"


class WaitlistStatus(StrEnum):
    ACTIVE = "active"
    PROMOTED = "promoted"
    CANCELLED = "cancelled"


class PublicationBatchStatus(StrEnum):
    DRAFT = "draft"
    PUBLISHING = "publishing"
    PUBLISHED = "published"
    FAILED = "failed"


class CancelDeadlineSource(StrEnum):
    DEFAULT = "default"
    OVERRIDE = "override"
