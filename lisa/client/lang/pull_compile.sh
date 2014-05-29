#!/bin/sh

tx pull -f -a
for i in *; do 
    if [ -e $i/LC_MESSAGES/lisa.po ]
    then
        msgfmt -o $i/LC_MESSAGES/lisa.mo $i/LC_MESSAGES/lisa.po
    fi
done 
