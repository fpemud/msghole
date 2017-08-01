#!/bin/bash

FILES="$(find ./python3 -name '*.py' | tr '\n' ' ')"
autopep8 -ia --ignore=E501,E402 ${FILES}