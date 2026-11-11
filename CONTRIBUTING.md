# Contributing

## Running the tests

The project has an offline test suite that needs no installs.

    python3 -m unittest discover -s tests
    BA_CONTRACT=contract_deploy.py python3 -m unittest discover -s tests
    python3 tools/make_deploy.py --check

## Changing the contract

Edit contract.py, then run python3 tools/make_deploy.py to rebuild contract_deploy.py.
Run the full suite again before opening a pull request.
