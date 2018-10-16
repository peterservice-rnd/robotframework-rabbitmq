RobotFramework RabbitMQ
=======================

|Build Status|

Short Description
-----------------

`Robot Framework`_ library for for working with RabbitMQ.

Installation
------------

Install the library from PyPI using pip:

::

    pip install robotframework-rabbitmq

Documentation
-------------

See keyword documentation for RabbitMQ library on `GitHub`_.

Example
-------

.. code:: robotframework

    *** Settings ***
    Library    RabbitMq
    Library    Collections

    *** Test Cases ***
    Simple Test
        Create Rabbitmq Connection    my_host_name    15672    5672    guest    guest    alias=rmq
        ${overview}=    Overview
        Log Dictionary    ${overview}
        Close All Rabbitmq Connections

License
-------

Apache License 2.0

.. _Robot Framework: http://www.robotframework.org
.. _GitHub: https://rawgit.com/peterservice-rnd/robotframework-rabbitmq/master/docs/RabbitMq.html

.. |Build Status| image:: https://travis-ci.org/peterservice-rnd/robotframework-rabbitmq.svg?branch=master
   :target: https://travis-ci.org/peterservice-rnd/robotframework-rabbitmq