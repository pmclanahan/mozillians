import datetime

from django.contrib import auth, messages
from django.contrib.auth import views as auth_views
from django.shortcuts import redirect, render

import commonware.log
from django_browserid.auth import get_audience
from django_browserid.views import Verify
from funfactory.urlresolvers import reverse
from tower import ugettext as _

from phonebook.models import Invite
from session_csrf import anonymous_csrf
from users import forms

log = commonware.log.getLogger('m.users')

get_invite = lambda c: Invite.objects.get(code=c, redeemed=None)


def logout(request, **kwargs):
    """Logout view that wraps Django's logout but always redirects.

    Django's contrib.auth.views logout method renders a template if the
    `next_page` argument is `None`, which we don't want. This view always
    returns an HTTP redirect instead.
    """
    return auth_views.logout(request, next_page=reverse('home'), **kwargs)


class Browserid(Verify):
    """View for dealing with Browserid callback"""

    def handle_user(self, request, user):
        if user.get_profile().is_complete():
            auth.login(request, user)
            return redirect(reverse('profile', args=[user.username]))
        else:
            request.session['authenticated_email'] = user.email
            return redirect(reverse('register'))


def password_reset_confirm(request, uidb36=None, token=None):
    """TODO: Legacy URL, keep around until 1.4 release."""
    return redirect('home')


@anonymous_csrf
def register(request):
    """
    Single-purpose view.
    Registers Users. Pulls out an invite code if it exists and auto validates
    the user if so.
    """
    if 'code' in request.GET:
        request.session['invite-code'] = request.GET['code']
        return redirect('home')

    if request.user.is_authenticated():
        return redirect(reverse('profile', args=[request.user.username]))

    authenticated_email = request.session.get('authenticated_email')
    if not authenticated_email:
        log.error('Browserid registration, but no verified email in session')
        return redirect('home')

    user = auth.authenticate(authenticated_email=authenticated_email)
    if not user:
        return redirect('home')

    form = forms.RegistrationForm(request.POST or None,
                                  instance=user.get_profile())

    if request.method == 'POST':
        if form.is_valid():
            form.save(user)
            auth.login(request, user)
            _update_invites(request)
            messages.info(request, _(u'Your account has been created.'))
            return redirect('profile', user.username)

    # When changing this keep in mind that the same view is used for
    # phonebook.edit_profile.
    # 'user' object must be passed in because we are not logged in
    return render(request, 'phonebook/edit_profile.html',
                  dict(form=form,
                       edit_form_action=reverse('register'),
                       mode='new',
                       profile=user.get_profile(),
                       user=user,
                       ))


def _update_invites(request):
    code = request.session.get('invite-code')
    if code:
        try:
            invite = get_invite(code)
            voucher = invite.inviter
        except Invite.DoesNotExist:
            msg = 'Invite code [%s], does not exist!' % code
            log.warning(msg)
            # If there is no invite, lets get out of here.
            return
    else:
        # If there is no invite, lets get out of here.
        return

    redeemer = request.user.get_profile()
    redeemer.vouch(voucher)
    invite.redeemed = datetime.datetime.now()
    invite.redeemer = redeemer
    invite.save()


def _set_already_exists_error(form):
    msg = _('Someone has already registered an account with %(email)s.')
    data = dict(email=form.cleaned_data['email'])
    del form.cleaned_data['email']
    error = _(msg % data)
    form._errors['email'] = form.error_class([error])
