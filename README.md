# Adam's Mail Tools

This is a collection of tools I use for processing my mail.

amt_fetchmail.py
-----------------

This processes messages on a remote IMAP server.

It is similar to fetchmail/getmail/others.  The main advantage is that it
allows custom classification logic, and it can then deliver messages both to
remote IMAP folders and to local folders based on the results of
classification.  The classification logic can be arbitrary python code.

I have tested this mostly against Exchange servers.  It avoids bugs in
Exchange's IMAP handling that I have run into in the past with fetchmail.

amt_classify.py
---------------

This script is useful for debugging your mail classification logic.  It can be
run on a single message from an mbox folder, and it will print the tags that
would be applied.

amt_urlview.py
--------------

This is a script which can be used as a helper program for mutt.  It is similar
to urlview, but allows custom logic for determining which URLs to display.  It
also supports automatically figuring out the URL you want to go to for given
message types, and directly going there instead of prompting you which URL you
want to use.

amt_prune.py
------------

This script can be used to prune old messages from IMAP folders.  In my case, I
have amt_fetchmail.py save all messages to a backup folder before processing
them.  amt_prune.py is useful for periodically cleaning up this backup folder.

amt_ldap.py
-----------

This script can query address information from an LDAP server.  It can be used
as a query_command setting for mutt.
