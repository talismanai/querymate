Installation
============

QueryMate can be installed via pip from PyPI:

.. code-block:: bash

    pip install querymate

Requirements
-----------

QueryMate requires:

* Python 3.11+
* FastAPI
* SQLModel
* Pydantic v2

These dependencies will be installed automatically when you install QueryMate.

Development Installation
----------------------

To install QueryMate for development:

.. code-block:: bash

    # Clone the repository
    git clone https://github.com/mauricioabreu/querymate.git
    cd querymate

    # Create a virtual environment
    python -m venv .venv
    source .venv/bin/activate  # On Windows: .venv\Scripts\activate

    # Install development dependencies
    pip install -e ".[dev]"

    # Run tests
    pytest

    # Build documentation
    cd docs
    make html 