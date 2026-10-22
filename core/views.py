"""Public entry point."""
from django.shortcuts import redirect


def home(request):
    """Open the event directory."""
    return redirect('hackathons:list')
