"""Public entry point."""
from django.shortcuts import render

from accounts.permissions import can_create_hackathon
from hackathons.models import Hackathon


def home(request):
    """Landing page: presentation of the platform and the upcoming public events."""
    upcoming = Hackathon.objects.filter(
        status__in=[Hackathon.Status.PUBLISHED, Hackathon.Status.ONGOING]).order_by('start_date')[:3]
    return render(request, 'core/home.html', {'upcoming': upcoming, 'can_create': can_create_hackathon(request.user)})
