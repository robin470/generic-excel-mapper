"""
Shared TargetField shape used throughout the pipeline (mapper,
transformer, validator, exporter) regardless of where it came from.
Templates now live in the DB (see db_models.py / templates_api.py) --
SEED_TARGET_FIELDS below exists only to seed a default template the
first time the app runs, so the app isn't empty on a fresh install.
"""

from dataclasses import dataclass, field


@dataclass
class TargetField:
    name: str
    description: str = ""
    aliases: list[str] = field(default_factory=list)
    data_type: str = "string"  # string | numeric | integer | decimal | email | date | boolean
    required: bool = False
    unique: bool = False
    pattern: str | None = None
    allowed_values: list | None = None
    min_length: int | None = None
    max_length: int | None = None


SEED_TARGET_FIELDS: list[TargetField] = [
    TargetField(
        name="customer_id",
        description="Unique customer identifier",
        aliases=["cust_id", "customer number", "client id", "id"],
        data_type="string",
        required=True,
        unique=True,
    ),
    TargetField(
        name="full_name",
        description="Customer full name",
        aliases=["name", "customer name", "client name"],
        data_type="string",
        required=True,
        min_length=2,
    ),
    TargetField(
        name="email",
        description="Customer email address",
        aliases=["email address", "e-mail", "contact email"],
        data_type="email",
        required=True,
        pattern=r"^[^@\s]+@[^@\s]+\.[^@\s]+$",
    ),
    TargetField(
        name="phone",
        description="Customer phone number",
        aliases=["phone number", "contact number", "mobile"],
        data_type="string",
        required=False,
    ),
    TargetField(
        name="signup_date",
        description="Date the customer signed up",
        aliases=["date joined", "created date", "registration date"],
        data_type="date",
        required=False,
    ),
    TargetField(
        name="country",
        description="Customer country",
        aliases=["nation", "country name"],
        data_type="string",
        required=False,
    ),
]