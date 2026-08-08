#!/usr/bin/bash
set -e
set -x

pushd .. &> /dev/null
pwd

# install twine: uv tool install twine
# upload to pypi  (check you have valid token, ~/.pypirc

twine upload dist/*


popd &> /dev/null




