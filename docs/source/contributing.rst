Contributing
===========

We love your input! We want to make contributing to QueryMate as easy and transparent as possible.

Development Setup
---------------

1. Fork the repository and clone your fork:

   .. code-block:: bash

       git clone https://github.com/yourusername/querymate.git
       cd querymate

2. Create a virtual environment and install dependencies:

   .. code-block:: bash

       python -m venv .venv
       source .venv/bin/activate  # On Windows: .venv\Scripts\activate
       uv pip install -e ".[dev]"

3. Create a branch for your changes:

   .. code-block:: bash

       git checkout -b feature/your-feature-name

Development Workflow
-----------------

1. Make your changes
2. Run the test suite:

   .. code-block:: bash

       pytest

3. Run code quality checks:

   .. code-block:: bash

       make lint
       make format
       python -m mypy .

4. Update documentation if needed:

   .. code-block:: bash

       cd docs
       make html

5. Commit your changes:

   .. code-block:: bash

       git add .
       git commit -m "Description of your changes"
       git push origin feature/your-feature-name

6. Submit a Pull Request

Pull Request Process
------------------

1. Update the README.md and documentation with details of changes if needed
2. Update the CHANGELOG.md with a note describing your changes
3. The PR will be merged once you have the sign-off of the maintainers

Code Style
---------

- Follow PEP 8 guidelines
- Use type hints
- Write docstrings for all public functions and classes
- Keep functions focused and small
- Write meaningful commit messages

Running Tests
-----------

The test suite can be run with pytest:

.. code-block:: bash

    # Run all tests
    pytest

    # Run tests with coverage
    pytest --cov=querymate

    # Run a specific test
    pytest tests/test_querymate.py -k test_name

Building Documentation
-------------------

The documentation is built using Sphinx:

.. code-block:: bash

    cd docs
    make html

The built documentation will be in `docs/_build/html/`.

Reporting Issues
--------------

When reporting issues:

1. Check if the issue already exists
2. Include:
   - Your Python version
   - QueryMate version
   - Minimal code example that reproduces the issue
   - Full error traceback if applicable
   - What you expected to happen
   - What actually happened

Feature Requests
--------------

We're always looking for suggestions to improve QueryMate. Feel free to:

1. Open an issue with the tag "enhancement"
2. Describe the feature you'd like to see
3. Why you need it
4. How it should work

Code of Conduct
-------------

This project and everyone participating in it is governed by our Code of Conduct.
By participating, you are expected to uphold this code. 