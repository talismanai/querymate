Defaults
========

This document summarizes all default parameters and configurations in Querymate.

Query Parameters
---------------

The following are the default parameters for query operations:

+----------------+------------------+------------------------------------------+
| Parameter      | Default Value    | Constraints                              |
+================+==================+==========================================+
| q              | {}               | None                                      |
+----------------+------------------+------------------------------------------+
| sort           | []               | None                                      |
+----------------+------------------+------------------------------------------+
| limit          | 10               | 1 <= limit <= 200                        |
+----------------+------------------+------------------------------------------+
| offset         | 0                | offset >= 0                               |
+----------------+------------------+------------------------------------------+
| fields         | []               | None (returns all fields)                 |
+----------------+------------------+------------------------------------------+

QueryBuilder Defaults
-------------------

The QueryBuilder class has the following default behaviors:

- If no fields are specified in ``select()``, all model fields are selected
- If no conditions are specified in ``filter()``, no filtering is applied
- If no sort parameters are specified in ``sort()``, no sorting is applied
- If no limit/offset is specified in ``limit_and_offset()``, all results are returned
- The ``build()`` method defaults to no filtering, sorting, or pagination if parameters are not specified

Development Environment
---------------------

Python Version
~~~~~~~~~~~~~

- Minimum Python version: 3.11

Dependencies
~~~~~~~~~~~

Core Dependencies
^^^^^^^^^^^^^^^

+----------------+------------------+
| Package        | Minimum Version  |
+================+==================+
| FastAPI        | 0.109.0         |
+----------------+------------------+
| SQLModel       | 0.0.14          |
+----------------+------------------+
| Pydantic       | 2.6.0           |
+----------------+------------------+
| SQLAlchemy     | 2.0.0           |
+----------------+------------------+

Development Dependencies
^^^^^^^^^^^^^^^^^^^^^^

+----------------+------------------+
| Package        | Minimum Version  |
+================+==================+
| pytest         | 8.0.0           |
+----------------+------------------+
| pytest-cov     | 4.1.0           |
+----------------+------------------+
| ruff           | 0.2.0           |
+----------------+------------------+
| black          | 24.1.0          |
+----------------+------------------+
| isort          | 5.13.0          |
+----------------+------------------+
| mypy           | 1.8.0           |
+----------------+------------------+
| sphinx         | 7.2.0           |
+----------------+------------------+
| sphinx-rtd-theme | 2.0.0        |
+----------------+------------------+
| httpx          | 0.27.0          |
+----------------+------------------+

Code Style and Linting
---------------------

Line Length
~~~~~~~~~~

- Ruff: 88 characters
- Black: 88 characters
- isort: 80 characters

Python Version Target
~~~~~~~~~~~~~~~~~~~

- Target Python version: 3.11

Linting Rules
~~~~~~~~~~~~

Ruff
^^^^

Selected Lints:
- E (pycodestyle errors)
- F (pyflakes)
- I (isort)
- N (pep8-naming)
- UP (pyupgrade)
- B (flake8-bugbear)
- RUF (ruff-specific)

Ignored Lints:
- E501 (line too long)
- N806 (camelCase in function)

isort Configuration
^^^^^^^^^^^^^^^^^

- Profile: black
- Multi-line output: 3
- Include trailing comma: true
- Force grid wrap: 0
- Use parentheses: true
- Ensure newline before comments: true

Type Checking (mypy)
-------------------

The following mypy settings are enabled by default:

- Python version: 3.11
- Warn return any: true
- Warn unused configs: true
- Disallow untyped defs: true
- Disallow incomplete defs: true
- Check untyped defs: true
- Disallow untyped decorators: true
- No implicit optional: true
- Warn redundant casts: true
- Warn unused ignores: true
- Warn no return: true
- Warn unreachable: true

Testing Configuration
-------------------

- Test paths: "tests" directory
- Test file pattern: "test_*.py" 