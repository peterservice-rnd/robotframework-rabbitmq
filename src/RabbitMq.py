# -*- coding: utf-8 -*-

import json
import requests
from requests.utils import quote
from robot.api import logger
from robot.utils import ConnectionCache
from amqp.connection import Connection
from amqp.basic_message import Message
from amqp.exceptions import NotFound
from socket import gaierror, error, timeout
from robot.libraries.BuiltIn import BuiltIn


class RequestConnection(object):
    """This class contains settings to connect to RabbitMQ via HTTP."""
    def __init__(self, host, port, username, password, timeout):
        """
        Initialization.

        *Args:*\n
        _host_ - server host name;\n
        _port_ - port number;\n
        _username_ - user name;\n
        _password_ - user password;\n
        _timeout_ - connection timeout;\n

        """
        self.host = host
        self.port = port
        self.url = 'http://{host}:{port}/api'.format(host=host, port=port)
        self.auth = (username, password)
        self.timeout = timeout

    def close(self):
        """Close connection."""
        pass


class BlockedConnection(Connection):
    """
    Wrapper over standard connection to RabbitMQ
    Allows to register connection lock events of the server
    """

    def __init__(self, **kwargs):
        """Constructor arguments are supplemented with
        callbacks to register blocking events

        Args:
            kwargs: Arguments of the parent class "Connection"
        """
        self.add_callback(self.block, 'on_blocked', kwargs)
        self.add_callback(self.unblock, 'on_unblocked', kwargs)
        super(BlockedConnection, self).__init__(**kwargs)
        self._blocked = False

    @staticmethod
    def add_callback(callback, key, args):
        """ Add our callback to existing one.

        Args:
            callback: callback.
            key: key.
            args: arguments.
        """
        if key in args:
            original_callback = args[key]

            def call_hook(**kwargs):
                callback(**kwargs)
                original_callback(**kwargs)

            args[key] = call_hook
        else:
            args[key] = callback

    def block(self):
        """
        Set connection blocking flag
        """
        self._blocked = True

    def unblock(self):
        """
        Unset connection blocking flag
        """
        self._blocked = False

    @property
    def blocked(self):
        """
        *Returns:*\n
            Connection blocking flag.
        """
        return self._blocked


class RabbitMq(object):
    """
    Library for working with RabbitMQ.

    == Dependencies ==
    | amqp | https://pypi.python.org/pypi/amqp |
    | requests | https://pypi.python.org/pypi/requests |
    | robot framework | http://robotframework.org |

    == Example ==
    | *Settings* | *Value* |
    | Library    | RabbitMq |
    | Library    | Collections |

    | *Test Cases* | *Action* | *Argument* | *Argument* | *Argument* | *Argument* | *Argument* |
    | Simple |
    |    | Create Rabbitmq Connection | my_host_name | 15672 | 5672 | guest | guest | alias=rmq |
    |    | ${overview}= | Overview |
    |    | Log Dictionary | ${overview} |
    |    | Close All Rabbitmq Connections |
    """

    ROBOT_LIBRARY_SCOPE = 'GLOBAL'

    def __init__(self):
        """ Initialization. """
        self._http_connection = None
        self._http_cache = ConnectionCache()
        self._amqp_connection = None
        self._amqp_cache = ConnectionCache()
        self._channel = None

    def _connect_to_amqp(self, host, port, username='guest', password='guest',
                         alias=None, virtual_host='/'):
        """ Connect to server via AMQP.

        *Args*:\n
            _host_: server host name.\n
            _port_: port number.\n
            _username_: user name.\n
            _password_: user password.\n
            _alias_: connection alias.\n
            _virtual_host_: virtual host name.\n

        *Returns:*\n
            Server connection object.
        """

        if port is None:
            BuiltIn().fail(msg="RabbitMq: port for connect is None")
        port = int(port)
        timeout = 15
        if virtual_host is None:
            BuiltIn().fail(msg="RabbitMq: virtual host for connect is None")
        virtual_host = str(virtual_host)

        parameters_for_connect = "host={host}, port={port}, username={username}, timeout={timeout}, alias={alias}".format(
            host=host,
            port=port,
            username=username,
            timeout=timeout,
            alias=alias)

        logger.debug('Connecting using : {params}'.format(params=parameters_for_connect))
        hostname = "{host}:{port}".format(host=host, port=port)
        try:
            self._amqp_connection = BlockedConnection(host=hostname,
                                                      userid=username,
                                                      password=password,
                                                      connect_timeout=timeout,
                                                      virtual_host=virtual_host,
                                                      confirm_publish=True)
        except (gaierror, error, IOError):
            BuiltIn().fail(msg="RabbitMq: Could not connect with following parameters: {params}".format(
                params=parameters_for_connect))
        self._channel = None
        return self._amqp_cache.register(self._amqp_connection, alias)

    def _connect_to_http(self, host, port, username, password, alias):
        """ Connect to server via HTTP.

        *Args*:\n
            _host_: server host name.\n
            _port_: port number.\n
            _username_: user name.\n
            _password_: user password.\n
            _alias_: connection alias.\n

        *Returns:*\n
            Server connection object.
        """
        if port is None:
            BuiltIn().fail(msg="RabbitMq: port for connect is None")
        port = int(port)
        timeout = 15
        parameters_for_connect = "host={host}, port={port}, username={username}, timeout={timeout}, alias={alias}".format(
            host=host,
            port=port,
            username=username,
            timeout=timeout,
            alias=alias)

        logger.debug('Connecting using : {params}'.format(params=parameters_for_connect))
        try:
            self._http_connection = RequestConnection(host, port, username, password, timeout)
        except (gaierror, error, IOError):
            BuiltIn().fail(msg="RabbitMq: Could not connect with following parameters: {params}".format(
                params=parameters_for_connect))
        return self._http_cache.register(self._http_connection, alias)

    def create_rabbitmq_connection(self, host, http_port, amqp_port, username,
                                   password, alias, vhost):
        """
        Connect to RabbitMq server.

        *Args:*\n
        _host_ - server host name;\n
        _http_port_ - port number of http-connection \n
        _amqp_port_ - port number of amqp-connection \n
        _username_ - user name;\n
        _password_ - user password;\n
        _alias_ - connection alias;\n
        _vhost_ - virtual host name;\n

        *Returns:*\n
        Current connection index.

        *Raises:*\n
        socket.error if connection cannot be created.

        *Example:*\n
        | Create Rabbitmq Connection | my_host_name | 15672 | 5672 | guest | guest | alias=rmq | vhost=/ |
        """

        self._connect_to_http(host=host, port=http_port, username=username,
                              password=password, alias=alias + "_http")
        self._connect_to_amqp(host=host, port=amqp_port, username=username,
                              password=password, alias=alias + "_amqp",
                              virtual_host=vhost)

    def switch_rabbitmq_connection(self, alias):
        """Switch between active RabbitMq connections using their index or alias.\n

        Alias is set in keyword [#Create Rabbitmq Connection|Create Rabbitmq Connection]
        which also returns the index of connection.\n

        *Args:*\n
        _alias_ - connection alias;

        *Returns:*\n
        Index of previous connection.

        *Example:*\n
        | Create Rabbitmq Connection | my_host_name_1 | 15672 | 5672 | guest | guest | alias=rmq1 |
        | Create Rabbitmq Connection | my_host_name_2 | 15672 | 5672 | guest | guest | alias=rmq2 |
        | Switch Rabbitmq Connection | rmq1 |
        | ${live}= | Is alive |
        | Switch Rabbitmq Connection | rmq2 |
        | ${live}= | Is alive |
        | Close All Rabbitmq Connections |
        """

        old_index = self._http_cache.current_index
        logger.debug('Switch active connection from {old} to {new}'
                     .format(old=old_index, new=alias))
        self._http_connection = self._http_cache.switch(alias + '_http')
        self._amqp_connection = self._amqp_cache.switch(alias + '_amqp')
        self._channel = None
        return old_index

    def disconnect_from_rabbitmq(self):
        """
        Close current RabbitMq connection.

        *Example:*\n
        | Create Rabbitmq Connection | my_host_name | 15672 | 5672 | guest | guest | alias=rmq |
        | Disconnect From Rabbitmq |
        """

        logger.debug('Close connection with : host={host}, port={port}'.format(
            host=self._http_connection.host, port=self._http_connection.port))
        self._http_connection.close()
        self._http_connection = None
        self._channel = None
        if self._amqp_connection is not None:
            if self._amqp_connection.connected:
                self._amqp_connection.close()
            self._amqp_connection = None

    def close_all_rabbitmq_connections(self):
        """
        Close all RabbitMq connections.

        This keyword is used to close all connections only in case if there are several open connections.
        Do not use keywords [#Disconnect From Rabbitmq|Disconnect From Rabbitmq] and
        [#Close All Rabbitmq Connections|Close All Rabbitmq Connections] together.\n

        After this keyword is executed the index returned by [#Create Rabbitmq Connection|Create Rabbitmq Connection]
        starts at 1.\n

        *Example:*\n
        | Create Rabbitmq Connection | my_host_name | 15672 | 5672 | guest | guest | alias=rmq |
        | Close All Rabbitmq Connections |
        """

        self._http_cache.close_all()
        self._http_connection = None
        self._amqp_cache.close_all()
        self._amqp_connection = None
        self._channel = None

    # AMQP API

    def _get_channel(self):
        """ Get channel from current connection.

        *Returns:*\n
            Channel.
        """
        if self._channel is None:
            self._channel = self._amqp_connection.channel()
        if self._amqp_connection.blocked:
            raise Exception('Connection is blocked')
        return self._channel

    def create_exchange(self, exchange_name, exchange_type, auto_delete=None,
                        durable=None, arguments=None):
        """
        Create exchange.

        The parameter _arguments_ is passed as dictionary.\n
        When defining "alternate-exchange" argument in the dictionary
        it is necessary to pass exchange's alternative name
        (if message cannot be routed it will be sent to alternative exchange).\n

        *Args:*\n
        _exchange_name_ - exchange name;\n
        _exchange_type_ - exchange type (direct, topic, headers, fanout);\n
        _auto_delete_ - delete exchange when all queues finish working with it (true, false);\n
        _durable_ - exchange survives when broker restarts (true, false);\n
        _arguments_ - additional arguments in dictionary format;\n

        *Example:*\n
        | ${list}= | Create List | list_value | ${TRUE} | 18080 |
        | ${args}= | Create Dictionary | arg1=value1 | arg2=${list} | alternate-exchange=amq.fanout |
        | Create Exchange | exchange_name=testExchange | exchange_type=fanout | auto_delete=false | durable=true | arguments=${args} |
        """

        exchange_name = str(exchange_name)
        exchange_type = str(exchange_type)
        logger.debug("Creating new exchange {ex} with type {t}"
                     .format(ex=exchange_name, t=exchange_type))
        self._get_channel().exchange_declare(exchange=exchange_name,
                                             type=exchange_type,
                                             durable=durable,
                                             auto_delete=auto_delete,
                                             arguments=arguments)

    def is_exchange_exist(self, name, exchange_type):
        """
        Check if exchange exists

        *Args:*\n
        _name_ - exchange name;\n
        _exchange_type_ - exchange type;\n

        *Example:*\n
        | ${is_exist}= | Is Exchange Exist | name='name' | exchange_type='direct' |
        | Should Be True | ${is_exist} |

        *Returns:*\n
        True if exchange exists otherwise False
        """

        name = str(name)
        exchange_type = str(exchange_type)
        try:
            self._get_channel().exchange_declare(exchange=name,
                                                 type=exchange_type,
                                                 passive=True)
            return True
        except NotFound:
            return False

    def delete_exchange(self, exchange_name):
        """
        Delete exchange.

        *Args:*\n
        _exchange_name_ - exchange name;\n

        *Example:*\n
        | Delete Exchange | exchange_name=testExchange |
        """

        exchange_name = str(exchange_name)
        self._get_channel().exchange_delete(exchange=exchange_name)

    def create_queue(self, queue_name, auto_delete=None, durable=None,
                     node=None, arguments=None):
        """
        Create queue.

        *Args:*\n
        _queue_name_ - queue name (quoted with requests.utils.quote);\n
        _auto_delete_ - delete queue when last subscriber unsubscribes from queue (true, false);\n
        _durable_ - queue survives when broker restarts (true, false);\n
        _node_ - RabbitMq node name;\n
        _arguments_ - additional arguments in dictionary format;\n

        *Example:*\n
        | ${list}= | Create List | list_value | ${FALSE} | 15240 |
        | ${args}= | Create Dictionary | arg1=value1 | arg2=${list} |
        | Create Queue | queue_name=testQueue | auto_delete=false | durable=true | node=rabbit@primary | arguments=${args} |
        """

        queue_name = str(queue_name)
        logger.debug('Create queue {n}'.format(n=queue_name))
        self._get_channel().queue_declare(queue=queue_name, durable=durable,
                                          auto_delete=auto_delete,
                                          arguments=arguments)

    def is_queue_exist(self, name):
        """
        Check if queue exists

        *Args:*\n
        _name_ - queue name

        *Example:*\n
        | ${exist}= | Is Queue Exist | name='queue' |
        | Should Be True | ${exist} |

        *Returns:*\n
        True if queue exists otherwise False
        """

        try:
            self._get_channel().queue_declare(queue=name, passive=True)
            return True
        except NotFound:
            return False

    def binding_exchange_with_queue(self, exchange_name, queue_name,
                                    routing_key='', arguments=None):
        """
        Create binding of exchange with queue.

        *Args:*\n
        _exchange_name_ - exchange name;\n
        _queue_name_ - queue name;\n
        _routing_key_ - routing key;\n
        _arguments_ - additional arguments in dictionary format;\n

        *Example:*\n
        | ${list}= | Create List | str1 | ${FALSE} |
        | ${args}= | Create Dictionary | arg1=value1 | arg2=${list} |
        | Binding Exchange With Queue | exchange_name=testExchange | queue_name=testQueue | routing_key=key | arguments=${args} |
        """

        queue_name = str(queue_name)
        exchange_name = str(exchange_name)
        logger.debug('Binding queue {q} to exchange {e}, with routing key {r}'
                     .format(q=queue_name, e=exchange_name, r=routing_key))
        self._get_channel().queue_bind(queue=queue_name, exchange=exchange_name,
                                       routing_key=routing_key,
                                       arguments=arguments)

    def unbind_queue(self, queue_name, exchange_name, routing_key='',
                     arguments=None):
        """
        Unbind queue from exchange.

        *Args:*\n
        _queue_name_ - queue name;\n
        _exchange_name_ - exchange name;\n
        _routing_key_ - routing key;\n
        _arguments_ - additional arguments in dictionary format;\n
        """

        queue_name = str(queue_name)
        exchange_name = str(exchange_name)
        logger.debug('Unbind queue {q} from exchange {e} with routing key {r}'
                     .format(q=queue_name, r=routing_key, e=exchange_name))
        self._get_channel().queue_unbind(queue=queue_name,
                                         exchange=exchange_name,
                                         routing_key=routing_key,
                                         arguments=arguments)

    def purge_queue(self, queue_name):
        """
        Purge queue.

        *Args:*\n
        _queue_name_ - queue name;\n
        """

        queue_name = str(queue_name)
        logger.debug('Purge queue {q}'.format(q=queue_name))
        self._get_channel().queue_purge(queue=queue_name)

    def delete_queue(self, queue_name):
        """
        Delete queue.

        *Args:*\n
        _queue_name_ - queue name;\n

        *Example:*\n
        | Delete Queue | queue_name=testQueue |
        """

        queue_name = str(queue_name)
        self._get_channel().queue_delete(queue=queue_name)

    def enable_consuming_messages_in_queue(self, queue_name, count, requeue,
                                           consumed_list):
        """
        Enable consuming messages in queue.

        *Args:*\n
        _queue_name_ - queue name;\n
        _count_ - number of messages to consume;\n
        _requeue_ - re-placing consumed message in the queue with setting of redelivered attribute (true, false);\n
        _consumed_list_ - list of delivery_tag of all consumed messages;\n

        *Returns:*\n
        Identifier of message handler in the queue.

        *Example:*\n
        | ${list}= | Create List |
        | Enable Consuming Messages In Queue | queue_name=${QUEUE_NAME} | count=1 | requeue=${FALSE} | consumed_list=${list} |
        | Log List | ${list} |
        """

        count = int(count)
        queue_name = str(queue_name)
        consumer_name = "consumer{name}".format(name=queue_name)

        def consumer_callback(message):
            """
            Callback for consuming messages from the queue.

            Processes specified number of messages and closes.

            *Args:*\n
            _message_ - message from the queue.
            """
            channel = message.channel
            tag = message.delivery_info['delivery_tag']
            logger.debug("Consume message {} - {}".format(tag, message.body))
            channel.basic_reject(tag, requeue)
            consumed_list.append(tag)
            if len(consumed_list) >= count:
                channel.basic_cancel(consumer_name)

        logger.debug('Begin consuming messages. Queue={q}, count={c}'
                     .format(q=queue_name, c=count))
        self._get_channel().basic_consume(queue=queue_name,
                                          consumer_tag=consumer_name,
                                          callback=consumer_callback)
        return consumer_name

    def publish_message(self, exchange_name, routing_key, payload, props=None):
        """
        Publish message to the queue.

        *Args:*\n
        _exchange_name_ - exchange name;\n
        _routing_key_ - routing key (quoted with requests.utils.quote);\n
        _payload_ - payload message;\n
        _props_ - additional arguments in dictionary format;\n
         Includes such keys as:\n
        - _content-type_ - message content type (shortstr);
        - _content_encoding_ - message encoding type (shortstr);
        - _application_headers_ - message headers table, a dictionary with keys of type string and values of types
         string | int | Decimal | datetime | dict values (table);
        - _delivery_mode_ - Non-persistent (1) or persistent (2) (octet);
        - _priority_ - message priority from 0 to 9 (octet);
        - _correlation_id_ - message identifier to which current message responds (shortstr);
        - _reply_to_ - commonly used to name a reply queue (shortstr);
        - _expiration_ - expiration date of message (shortstr);
        - _message_id_ - message identifier (shortstr);
        - _timestamp_ - timestamp of sending message (shortstr);
        - _type_ - message type (shortstr);
        - _user_id_ - user-sender identifier (shortstr);
        - _app_id_ - application identifier (shortstr);
        - _cluster_id_ - cluster identifier (shortstr);\n

        *Attention:*\n

        When using library in robot-files parameters (props)
         must be cast to the correct type.\n
        Example:\n
        | ${delivery_mode}= | Convert To Integer | 2 |
        This is due to the feature of RabbitMq library.\n

        *Example:*\n
        | ${list_headers}= | Create List | head_value | 2 | ${TRUE} |
        | ${headers_dict}= | Create Dictionary | head1=val1 | head2=${list_headers} |
        | ${prop_dict}= | Create Dictionary | application_headers=${headers_dict} | content-type=text/plain | priority=1 | expiration=1410966000 | message_id=101 | user_id=guest |
        | Publish Message | exchange_name=testExchange | routing_key=testQueue | payload=message body | props=${prop_dict} |
        """

        if props is None:
            props = {}
        exchange_name = str(exchange_name)
        routing_key = str(routing_key)
        logger.debug('Publish message to {exc} with routing {r}'
                     .format(exc=exchange_name, r=routing_key))
        msg = Message(payload, **props)
        self._get_channel().basic_publish(msg, exchange_name, routing_key)

    def process_published_message_in_queries(self, waiting=1):
        """
        Send processing of published message in queues to handler.\n
        May end with exception if handler is not installed or there are no messages in queue.\n

        *Args:*\n
        _waiting_ - server response timeout.
        """

        waiting = int(waiting)
        try:
            self._amqp_connection.drain_events(waiting)
        except timeout:
            pass

    def enable_message_sending_confirmation(self, confirmed_list,
                                            activate=True):
        """
        Enable processing of successful message sending confirmation in the exchange servers.\n
        If message is successfully sent to confirmed_list, delivery_tag of the message is added.\n

        *Args:*\n
        _confirmed_list_ - list in which all the delivery tag of sent messages are saved;\n
        _activate_ - indicates that message sending listener should start;\n

        *Example:*\n
        | ${list}= | Create List |
        | Enable Message Sending Confirmation | confirmed_list=${list} |
        | Publish Message | exchange_name=${EXCHANGE_NAME} | routing_key=${ROUTING_KEY} | payload=message body |
        | Process Published Message In Queries |
        | Length Should Be | ${list} | 1 |
        """

        def confirm_callback(delivery_tag, multiple):
            """
            Called when sending message notification is received.
            """
            logger.debug('Capture confirm message with tag={tag}'
                         .format(tag=delivery_tag))
            confirmed_list.append(delivery_tag)

        self._get_channel().confirm_select()
        logger.debug('Begin checking confirm publish')
        if activate is True:
            self._get_channel().events['basic_ack'].add(confirm_callback)
        else:
            self._get_channel().events['basic_ack'].remove(confirm_callback)

    # Manager API

    @staticmethod
    def _prepare_request_headers(body=None):
        """
        Headers definition for HTTP-request.
        Args:*\n
            _body_: HTTP-request body.

        *Returns:*\n
            Dictionary with headers for HTTP-request.
        """
        headers = {}
        if body:
            headers["Content-Type"] = "application/json"
        return headers

    @staticmethod
    def _quote_vhost(vhost):
        """ Vhost quote.

        *Args:*\n
            _vhost_: vhost name for quoting.

        *Returns:*\n
            Quoted name of vhost.
        """
        if vhost == '/':
            vhost = '%2F'
        if vhost != '%2F':
            vhost = quote(vhost)
        return vhost

    def is_alive(self):
        """
        Rabbitmq health check.

        Sends GET-request : 'http://<host>:<port>/api/' and checks response status code.\n

        *Returns:*\n
        bool True if return code is 200.
        bool False in all other cases.

        *Raises:*\n
        RequestException if it is not possible to send GET-request.

        *Example:*\n
        | ${live}= | Is Alive |
        =>\n
        True
        """
        try:
            response = requests.get(self._http_connection.url,
                                    auth=self._http_connection.auth,
                                    headers=self._prepare_request_headers(),
                                    timeout=self._http_connection.timeout)
        except requests.exceptions.RequestException as e:
            raise Exception('Could not send request: {0}'.format(e))
        logger.debug('Response status={0}'.format(response.status_code))
        return response.status_code == 200

    def overview(self):
        """ Information about RabbitMq server.

        *Returns:*\n
        Dictionary with information about the server.

        *Raises:*\n
        raise HTTPError if the HTTP request returned an unsuccessful status code.

        *Example:*\n
        | ${overview}=  |  Overview |
        | Log Dictionary | ${overview} |
        | ${version}= | Get From Dictionary | ${overview}  |  rabbitmq_version |
        =>\n
        Dictionary size is 14 and it contains following items:
        | cluster_name | rabbit@primary |
        | contexts | [{u'node': u'rabbit@primary', u'path': u'/', u'description': u'RabbitMQ Management', u'port': 15672}, {u'node': u'rabbit@primary', u'path': u'/web-stomp-examples', u'description': u'WEB-STOMP: examples', u'port': 15670}] |
        | erlang_full_version | Erlang R16B03 (erts-5.10.4) [source] [64-bit] [async-threads:30] [kernel-poll:true] |
        | erlang_version | R16B03 |
        | exchange_types | [{u'enabled': True, u'name': u'fanout', u'description': u'AMQP fanout exchange, as per the AMQP specification'}, {u'internal_purpose': u'federation', u'enabled': True, u'name': u'x-federation-upstream', u'description': u'Federation upstream helper exchange'}, {u'enabled': True, u'name': u'direct', u'description': u'AMQP direct exchange, as per the AMQP specification'}, {u'enabled': True, u'name': u'headers', u'description': u'AMQP headers exchange, as per the AMQP specification'}, {u'enabled': True, u'name': u'topic', u'description': u'AMQP topic exchange, as per the AMQP specification'}, {u'enabled': True, u'name': u'x-consistent-hash', u'description': u'Consistent Hashing Exchange'}] |
        | listeners | [{u'node': u'rabbit@primary', u'ip_address': u'::', u'protocol': u'amqp', u'port': 5672}, {u'node': u'rabbit@primary', u'ip_address': u'::', u'protocol': u'clustering', u'port': 25672}, {u'node': u'rabbit@primary', u'ip_address': u'::', u'protocol': u'mqtt', u'port': 1883}, {u'node': u'rabbit@primary', u'ip_address': u'::', u'protocol': u'stomp', u'port': 61613}] |
        | management_version | 3.3.0 |
        | message_stats | {u'publish_details': {u'rate': 0.0}, u'confirm': 85, u'deliver_get': 85, u'publish': 85, u'confirm_details': {u'rate': 0.0}, u'get_no_ack': 85, u'get_no_ack_details': {u'rate': 0.0}, u'deliver_get_details': {u'rate': 0.0}} |
        | node | rabbit@primary |
        | object_totals | {u'connections': 0, u'channels': 0, u'queues': 2, u'consumers': 0, u'exchanges': 10} |
        | queue_totals | {u'messages_details': {u'rate': 0.0}, u'messages': 0, u'messages_ready': 0, u'messages_ready_details': {u'rate': 0.0}, u'messages_unacknowledged': 0, u'messages_unacknowledged_details': {u'rate': 0.0}} |
        | rabbitmq_version | 3.3.0 |
        | statistics_db_node | rabbit@primary |
        | statistics_level | fine |

        ${version} = 3.3.0
        """
        url = self._http_connection.url + '/overview'
        response = requests.get(url, auth=self._http_connection.auth,
                                headers=self._prepare_request_headers(),
                                timeout=self._http_connection.timeout)
        response.raise_for_status()
        return response.json()

    def connections(self):
        """ List of open connections.

        *Returns:*\n
            List of open connections in JSON format.

        *Raises:*\n
            raise HTTPError if the HTTP request returned an unsuccessful status code.
        """
        url = self._http_connection.url + '/connections'
        response = requests.get(url, auth=self._http_connection.auth,
                                headers=self._prepare_request_headers(),
                                timeout=self._http_connection.timeout)
        response.raise_for_status()
        return response.json()

    def get_name_of_all_connections(self):
        """ List with names of all open connections.

        *Returns:*\n
            List with names of all open connections.
        """
        return [item['name'] for item in self.connections()]

    def channels(self):
        """ List of open channels.

        *Returns:*\n
             List of open channels in JSON format.
        *Raises:*\n
            raise HTTPError if the HTTP request returned an unsuccessful status code.
        """
        url = self._http_connection.url + '/channels'
        response = requests.get(url, auth=self._http_connection.auth,
                                headers=self._prepare_request_headers(),
                                timeout=self._http_connection.timeout)
        response.raise_for_status()
        return response.json()

    def get_exchange(self, exchange_name, vhost='%2F'):
        """ Get information about exchange.
        Parameters are quoted with requests.utils.quote.

        *Args:*\n
        _exchange_name_ - exchange name;\n
        _vhost_ - virtual host name;\n

        *Returns:*\n
            Dictionary with information about exchange.

        *Raises:*\n
            raise HTTPError if the HTTP request returned an unsuccessful status code.

        *Example:*\n
        | ${exchange}= | Get Exchange | exchange_name=testExchange | vhost=/ |
        | Log Dictionary | ${exchange}    |
        | ${value}= | Get From Dictionary | ${exchange} | name |
        | Log | ${value} |
        =>\n
        Dictionary size is 9 and it contains following items:
        | arguments | {u'arg1': u'value1', u'arg2': [u'list_value', True, u'18080'], u'alternate-exchange': u'amq.topic'} |
        | auto_delete | False |
        | durable | True |
        | incoming | [] |
        | internal | False |
        | name | testExchange |
        | outgoing | [] |
        | type | fanout |
        | vhost | / |

        ${value} = testExchange
        """
        path = '/exchanges/{vhost}/{name}'.format(
            vhost=self._quote_vhost(vhost), name=quote(exchange_name))
        response = requests.get(self._http_connection.url + path,
                                auth=self._http_connection.auth,
                                headers=self._prepare_request_headers(),
                                timeout=self._http_connection.timeout)
        response.raise_for_status()
        return response.json()

    def exchanges(self):
        """ List of exchanges.

        *Returns:*\n
            List of exchanges in JSON format.

        *Raises:*\n
            raise HTTPError if the HTTP request returned an unsuccessful status code.

        *Example:*\n
        | ${exchanges}=  |  Exchanges |
        | Log List  |  ${exchanges} |
        | ${item}=  |  Get From list  |  ${exchanges}  |  1 |
        | ${name}=  |  Get From Dictionary  |  ${q}  |  name  |
        =>\n
        List length is 8 and it contains following items:
        | 0 | {u'name': u'', u'durable': True, u'vhost': u'/', u'internal': False, u'message_stats': [], u'arguments': {}, u'type': u'direct', u'auto_delete': False} |
        | 1 | {u'name': u'amq.direct', u'durable': True, u'vhost': u'/', u'internal': False, u'message_stats': [], u'arguments': {}, u'type': u'direct', u'auto_delete': False} |
        ...\n
        ${name} = amq.direct
        """

        url = self._http_connection.url + '/exchanges'
        response = requests.get(url, auth=self._http_connection.auth,
                                headers=self._prepare_request_headers(),
                                timeout=self._http_connection.timeout)
        response.raise_for_status()
        return response.json()

    def get_names_of_all_exchanges(self):
        """ List of names of all exchanges.

        *Returns:*\n
            List of names of all exchanges.

        *Example:*\n
        | ${names}=  |  Get Names Of All Exchanges |
        | Log List  |  ${names} |
        =>\n
        | List has one item:
        | amq.direct
        """
        return [item['name'] for item in self.exchanges()]

    def get_exchanges_on_vhost(self, vhost='%2F'):
        """ List of exchanges on virtual host.

        *Returns:*\n
            List of exchanges in JSON format.

        *Raises:*\n
            raise HTTPError if the HTTP request returned an unsuccessful status code.

        *Args:*\n
        _vhost_ - virtual host name (quoted with requests.utils.quote);
        """

        url = self._http_connection.url + '/exchanges/' + self._quote_vhost(vhost)
        response = requests.get(url, auth=self._http_connection.auth,
                                headers=self._prepare_request_headers(),
                                timeout=self._http_connection.timeout)
        response.raise_for_status()
        return response.json()

    def get_names_of_exchanges_on_vhost(self, vhost='%2F'):
        """List of exchanges names on virtual host.

        *Args:*\n
        _vhost_: virtual host name (quoted with requests.utils.quote);

        *Returns:*\n
            List of exchanges names.

        *Example:*\n
        | ${names}=  |  Get Names Of Exchanges On Vhost |
        | Log List  |  ${names} |
        =>\n
        | List has one item:
        | federation: ex2 -> rabbit@server.net.ru
        """
        return [item['name'] for item in self.get_exchanges_on_vhost(vhost)]

    def get_queue(self, queue_name, vhost='%2F'):
        """
        Get information about queue.

        Parameters are quoted with requests.utils.quote.

        *Args:*\n
        _queue_name_ - queue name;\n
        _vhost_ - virtual host name (quoted with requests.utils.quote);\n

        *Returns:*\n
        Dictionary with information about queue.

        *Raises:*\n
        raise HTTPError if the HTTP request returned an unsuccessful status code.

        *Example:*\n
        | ${queue}= | Get Queue | queue_name=testQueue | vhost=/ |
        | Log Dictionary | ${queue} |
        | ${value}= | Get From Dictionary | ${queue} | name |
        | Log | ${value} |
        =>\n
        Dictionary size is 23 and it contains following items:
        | arguments | {u'arg1': u'value1', u'arg2': [u'list_value', False, u'15240']} |
        | auto_delete | False |
        | backing_queue_status | {u'q1': 0, u'q3': 0, u'q2': 0, u'q4': 0, u'avg_ack_egress_rate': 0.0, u'ram_msg_count': 0, u'ram_ack_count': 0, u'len': 0, u'persistent_count': 0, u'target_ram_count': u'infinity', u'next_seq_id': 0, u'delta': [u'delta', u'undefined', 0, u'undefined'], u'pending_acks': 0, u'avg_ack_ingress_rate': 0.0, u'avg_egress_rate': 0.0, u'avg_ingress_rate': 0.0} |
        | consumer_details | [] |
        | consumer_utilisation | |
        | consumers | 0 |
        | deliveries | [] |
        | durable | True |
        | exclusive_consumer_tag | |
        | idle_since | 2014-09-16 7:37:35 |
        | incoming | [{u'stats': {u'publish_details': {u'rate': 0.0}, u'publish': 5}, u'exchange': {u'vhost': u'/', u'name': u'testExchange'}}] |
        | memory | 34528 |
        | messages | 0 |
        | messages_details | {u'rate': 0.0} |
        | messages_ready | 0 |
        | messages_ready_details | {u'rate': 0.0} |
        | messages_unacknowledged | 0 |
        | messages_unacknowledged_details | {u'rate': 0.0} |
        | name | testQueue |
        | node | rabbit@primary |
        | policy | |
        | state | running |
        | vhost | / |

        ${value} = testQueue
        """
        path = '/queues/{vhost}/{name}'.format(
            vhost=self._quote_vhost(vhost), name=quote(queue_name))
        response = requests.get(self._http_connection.url + path,
                                auth=self._http_connection.auth,
                                headers=self._prepare_request_headers(),
                                timeout=self._http_connection.timeout)
        response.raise_for_status()
        return response.json()

    def queues(self):
        """ List of queues.

        *Returns:*\n
            List of queues in JSON format.

        *Raises:*\n
            raise HTTPError if the HTTP request returned an unsuccessful status code.
        """
        url = self._http_connection.url + '/queues'
        response = requests.get(url, auth=self._http_connection.auth,
                                headers=self._prepare_request_headers(),
                                timeout=self._http_connection.timeout)
        response.raise_for_status()
        return response.json()

    def get_queues_on_vhost(self, vhost='%2F'):
        """ List of queues on virtual host.

        *Args:*\n
        _vhost_ - virtual host name (quoted with requests.utils.quote);\n

        *Returns:*\n
            List of queues in JSON format.

        *Raises:*\n
            raise HTTPError if the HTTP request returned an unsuccessful status code.
        """
        url = self._http_connection.url + '/queues/' + self._quote_vhost(vhost)
        response = requests.get(url, auth=self._http_connection.auth,
                                headers=self._prepare_request_headers(),
                                timeout=self._http_connection.timeout)
        response.raise_for_status()
        return response.json()

    def get_names_of_queues_on_vhost(self, vhost='%2F'):
        """
        List of queues names on virtual host.

        *Args:*\n
        _vhost_: virtual host name (quoted with requests.utils.quote);

        *Returns:*\n
            List of queues names.

        *Example:*\n
        | ${names}=  |  Get Names Of Queues On Vhost |
        | Log List  |  ${names} |
        =>\n
        | List has one item:
        | federation: ex2 -> rabbit@server.net.ru
        """
        return [item['name'] for item in self.get_queues_on_vhost(vhost)]

    def get_binding_exchange_with_queue_list(self, exchange_name, queue_name,
                                             vhost='%2F'):
        """
        Get information about bindings of exchange with queue.

        Parameters are quoted with requests.utils.quote.

        *Args:*\n
        _exchange_name_ - exchange name;\n
        _queue_name_ - queue name;\n
        _vhost_ - virtual host name (quoted with requests.utils.quote);\n

        *Returns:*\n
        List of bindings of exchange with queue in JSON format.

        *Raises:*\n
        raise HTTPError if the HTTP request returned an unsuccessful status code.

        *Example:*\n
        | @{bind}= | Get Binding Exchange With Queue List | exchange_name=testExchange | queue_name=testQueue | vhost=/ |
        | Log Dictionary | ${bind[0]} |
        | Log | ${bind[0]["vhost"]} |
        =>\n
        Dictionary size is 7 and it contains following items:
        | arguments | {u'arg1': u'value1', u'arg2': [u'str1', False]} |
        | destination | testQueue |
        | destination_type | queue |
        | properties_key | ~2_oPmnDANCoVhkSJTkivZw |
        | routing_key: | |
        | source | testExchange |
        | vhost: | / |
        """
        path = '/bindings/{vhost}/e/{exchange}/q/{queue}'.format(
            vhost=self._quote_vhost(vhost),
            exchange=quote(exchange_name),
            queue=quote(queue_name))

        response = requests.get(self._http_connection.url + path,
                                auth=self._http_connection.auth,
                                headers=self._prepare_request_headers(),
                                timeout=self._http_connection.timeout)
        response.raise_for_status()
        return response.json()

    def get_message(self, queue_name, count, requeue, encoding, truncate=None,
                    vhost='%2F', ackmode='ack_requeue_true'):
        """
        Get message from the queue.

        *Args:*\n
        _queue_name_ - queue name;\n
        _count_ - number of messages to get;\n
        _requeue_ - re-placing received message in the queue with setting of redelivered attribute (true, false);\n
        _encoding_ - message encoding (auto, base64);\n
        _truncate_ - size of the message split (in bytes) in case it is greater than specified parameter (optional);\n
        _vhost_ - virtual host name (quoted with requests.utils.quote);\n
        _ackmode_ - determines whether the messages will be removed from the queue.
        If ackmode is ack_requeue_true or reject_requeue_true they will be requeued.
        If ackmode is ack_requeue_false or reject_requeue_false they will be removed;\n

        *Returns:*\n
        List with information about returned messages in dictionary format.
        Body of the message in the dictionary is "payload" key.

        *Raises:*\n
        raise HTTPError if the HTTP request returned an unsuccessful status code.

        *Example:*\n
        | ${msg}= | Get Message | queue_name=testQueue | count=2 | requeue=false | encoding=auto | truncate=50000 | vhost=/ |
        | Log List | ${msg} |
        =>\n
        List length is 5 and it contains following items:
        | 0 | {u'payload': u'message body 0', u'exchange': u'testExchange', u'routing_key': u'testQueue', u'payload_bytes': 14, u'message_count': 4, u'payload_encoding': u'string', u'redelivered': False, u'properties': []} |
        | 1 | {u'payload': u'message body 1', u'exchange': u'testExchange', u'routing_key': u'testQueue', u'payload_bytes': 14, u'message_count': 3, u'payload_encoding': u'string', u'redelivered': False, u'properties': []} |
        | ... |
        """
        path = '/queues/{vhost}/{name}/get'.format(
            vhost=self._quote_vhost(vhost), name=quote(queue_name))
        body = {"count": count, "requeue": requeue, "encoding": encoding, "ackmode": ackmode}
        if truncate is not None:
            body["truncate"] = truncate
        response = requests.post(self._http_connection.url + path,
                                 auth=self._http_connection.auth,
                                 headers=self._prepare_request_headers(body=body),
                                 data=json.dumps(body),
                                 timeout=self._http_connection.timeout)
        response.raise_for_status()
        return response.json()

    def vhosts(self):
        """ List of virtual hosts.
        *Returns:*\n
            List of virtual hosts in JSON format.

        *Raises:*\n
            raise HTTPError if the HTTP request returned an unsuccessful status code.
        """
        url = self._http_connection.url + '/vhosts'
        response = requests.get(url, auth=self._http_connection.auth,
                                headers=self._prepare_request_headers(),
                                timeout=self._http_connection.timeout)
        response.raise_for_status()
        return response.json()

    def nodes(self):
        """ List of nodes.

        *Returns:*\n
            List of nodes in JSON format.

        *Raises:*\n
            raise HTTPError if the HTTP request returned an unsuccessful status code.
        """
        url = self._http_connection.url + '/nodes'
        response = requests.get(url, auth=self._http_connection.auth,
                                headers=self._prepare_request_headers(),
                                timeout=self._http_connection.timeout)
        response.raise_for_status()
        return response.json()

    def _cluster_name(self):
        """ List of clusters.

        *Returns:*\n
            List of clusters in JSON format.

        *Raises:*\n
            raise HTTPError if the HTTP request returned an unsuccessful status code.
        """
        url = self._http_connection.url + '/cluster-name'
        response = requests.get(url, auth=self._http_connection.auth,
                                headers=self._prepare_request_headers(),
                                timeout=self._http_connection.timeout)
        response.raise_for_status()
        return response.json()
