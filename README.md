# RobotFramework RabbitMQ

[![Build Status](https://travis-ci.org/peterservice-rnd/robotframework-rabbitmq.svg?branch=master)](https://travis-ci.org/peterservice-rnd/robotframework-rabbitmq)

Short Description
---

[Robot Framework](http://www.robotframework.org) library for working with RabbitMQ.

Installation
---

```
pip install robotframework-rabbitmq
```

## Documentation

See keyword documentation for RabbitMQ library on [GitHub](https://github.com/peterservice-rnd/robotframework-rabbitmq/tree/master/docs).

Example
---
```robot
*** Settings ***
Library           RabbitMq
Library           Collections

*** Test Cases ***
Simple
    Create Rabbitmq Connection    my_host_name    15672    5672    guest    guest    alias=rmq
    ${overview}=    Overview
    Log Dictionary    ${overview}
    Close All Rabbitmq Connections
```

License
---

Apache License 2.0