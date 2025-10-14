from django import template

register = template.Library()

@register.filter
def get_field(form, field_name):
    """Get a field from the form by name"""
    return form.fields.get(field_name)

@register.filter
def add(value, arg):
    """Concatenate two values"""
    return str(value) + str(arg)

@register.filter
def has_errors(field):
    """Check if a field has errors"""
    return field.errors