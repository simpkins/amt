This is a custom IMAP implementation for python.

I originally started out using the existing imaplib / imaplib2 modules, but
they seemed to have a number of limitations, and did not have good support for
IDLE.  (imaplib2 supported it, but required an awkward threading model.)
