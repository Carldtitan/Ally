/*
 *   File:   form.js
 *
 *   Desc:   Validates the sign up form when it is submitted.
 *
 *   Follows the W3C WAI Forms Tutorial, User Notifications, "After submit":
 *   https://www.w3.org/WAI/tutorials/forms/notifications/
 *   The label gets an "Error:" prefix, the message is tied to the field with
 *   aria-describedby, and focus moves to the field with the error.
 *   aria-invalid follows WCAG technique ARIA21. The success message is a
 *   role="status" region, following WCAG technique ARIA22.
 */

'use strict';

window.addEventListener('load', function () {
  var form = document.getElementById('signup');
  var item = document.getElementById('email_item');
  var email = document.getElementById('email');
  var prefix = document.getElementById('email_prefix');
  var message = document.getElementById('email_error');
  var status = document.getElementById('signup_status');

  form.addEventListener('submit', function (event) {
    event.preventDefault();

    var error = '';
    if (email.value.trim() === '') {
      error = 'Enter your email address.';
    } else if (email.validity.typeMismatch) {
      error = 'Enter an email address in the format name@example.com.';
    }

    if (error) {
      item.className = 'form_item error';
      prefix.textContent = 'Error:';
      message.textContent = error;
      email.setAttribute('aria-invalid', 'true');
      status.textContent = '';
      email.focus();
    } else {
      item.className = 'form_item';
      prefix.textContent = '';
      message.textContent = '';
      email.removeAttribute('aria-invalid');
      status.textContent = 'Thank you. Your details were submitted.';
    }
  });
});
