# -*- coding: utf-8 -*- # noqa: E999

import json
import logging
from typing import Any, Dict, List, Optional, Tuple, Type, Union
from urllib.parse import quote

import pika
import requests
from pika import BaseConnection
from pika.adapters.blocking_connection import BlockingChannel
from pika.connection import Parameters
from pika.frame import Method as FrameMethod
from pika.spec import Basic, BasicProperties, Connection
from pika.exceptions import ChannelClosed, IncompatibleProtocolError
from robot.api import logger
from robot.utils import ConnectionCache
from robot.libraries.BuiltIn import BuiltIn
from socket import gaierror, error

RabbitMqMessage = Union[Tuple[Dict[str, Any], Dict[str, Any], str], Tuple[None, None, None]]  # noqa: 993


class RequestConnection(object):
    """This class contains settings to connect to RabbitMQ via HTTP."""
    def __init__(self, host: str, port: Union[int, str], username: str, password: str, timeout: int) -> None:
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
        self.url = f'http://{host}:{port}/api'
        self.auth = (username, password)
        self.timeout = timeout

    def close(self) -> None:
        """Close connection."""
        pass


class BlockedConnection(pika.BlockingConnection):
    """
    Wrapper over standard connection to RabbitMQ
    Allows to register connection lock events of the server
    """
    def __init__(self, parameters: Parameters = None, impl_class: Type[BaseConnection] = None) -> None:
        """Constructor arguments are supplemented with
        callbacks to register blocking events

        Args:
            parameters: connection parameters instance or non-empty sequence of them;
            impl_class: implementation class (for test/debugging only).
        """
        super(BlockedConnection, self).__init__(parameters=parameters, _impl_class=impl_class)
        self.add_on_connection_blocked_callback(self.on_blocked)
        self.add_on_connection_unblocked_callback(self.on_unblocked)
        self._blocked = False

    def on_blocked(self, method: Connection.Blocked) -> None:
        """
        Set connection blocking flag.

        Args:
            method: the method frame's `method` member is of type `pika.spec.Connection.Blocked`.
        """
        self._blocked = True

    def on_unblocked(self, method: Connection.Unblocked) -> None:
        """
        Unset connection blocking flag.

        Args:
            method: the method frame's `method` member is of type `pika.spec.Connection.Unblocked`.
        """
        self._blocked = False

    @property
    def blocked(self) -> bool:
        """
        *Returns:*\n
            Connection blocking flag.
        """
        return self._blocked

    def close(self, reply_code: int = 200, reply_text: str = 'Normal shutdown') -> None:
        """Close AMQP connection.

        Args:
            reply_code: the code number for the close.
            reply_text: the text reason for the close.
        """
        if self.is_open:
            super().close(reply_code=reply_code, reply_text=reply_text)
        else:
            logger.debug("Connection is already closed.")


class RabbitMq(object):
    """
    Library for working with RabbitMQ.

    == Dependencies ==
    | pika | https://pypi.org/project/pika/ |
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

    def __init__(self) -> None:
        """ Initialization. """
        self._http_connection: Optional[RequestConnection] = None
        self._http_cache = ConnectionCache()
        self._amqp_connection: Optional[BlockedConnection] = None
        self._amqp_cache = ConnectionCache()
        self._channel: Optional[BlockingChannel] = None
        logging.getLogger("pika").setLevel(logging.WARNING)

    @property
    def http_connection(self) -> RequestConnection:
        """Get current http connection to RabbitMQ.

        *Raises:*\n
            RuntimeError: if there isn't any open connection.

        *Returns:*\n
            Current http connection to to RabbitMQ.
        """
        if self._http_connection is None:
            raise RuntimeError('There is no open http connection to RabbitMQ.')
        return self._http_connection

    @property
    def amqp_connection(self) -> BlockedConnection:
        """Get current ampq connection to RabbitMQ.

        *Raises:*\n
            RuntimeError: if there isn't any open connection.

        *Returns:*\n
            Current ampq connection to to RabbitMQ.
        """
        if self._amqp_connection is None:
            raise RuntimeError('There is no open ampq connection to RabbitMQ.')
        return self._amqp_connection

    def _connect_to_amqp(self, host: str, port: Union[int, str], username: str = 'guest', password: str = 'guest',
                         alias: str = None, virtual_host: str = '/', socket_timeout: int = 15,
                         heartbeat_timeout: int = 600, blocked_timeout: int = 300) -> int:
        """ Connect to server via AMQP.

        *Args*:\n
            _host_: server host name.\n
            _port_: port number.\n
            _username_: user name.\n
            _password_: user password.\n
            _alias_: connection alias.\n
            _virtual_host_: virtual host name;\n
            _socket_timeout_: socket connect timeout;\n
            _heartbeat_timeout_: AMQP heartbeat timeout negotiation during connection tuning;\n
            _blocked_timeout_: timeout for the connection to remain blocked.\n

        *Returns:*\n
            Server connection index.
        """
        if port is None:
            BuiltIn().fail(msg="RabbitMq: port for connect is None")
        port = int(port)
        if virtual_host is None:
            BuiltIn().fail(msg="RabbitMq: virtual host for connect is None")
        virtual_host = str(virtual_host)

        parameters_for_connect = \
            f"host={host}, port={port}, username={username}, timeout={socket_timeout}, alias={alias}"

        logger.debug(f'Connecting using : {parameters_for_connect}')

        credentials = pika.PlainCredentials(username=username, password=password)
        conn_params = pika.ConnectionParameters(host=host, port=port,
                                                credentials=credentials,
                                                virtual_host=virtual_host,
                                                socket_timeout=socket_timeout,
                                                blocked_connection_timeout=blocked_timeout,
                                                heartbeat=heartbeat_timeout)
        try:
            self._amqp_connection = BlockedConnection(parameters=conn_params)
        except (gaierror, error, IOError, IncompatibleProtocolError):
            BuiltIn().fail(msg=f"RabbitMq: Could not connect with following parameters: {parameters_for_connect}")
        self._channel = None
        return self._amqp_cache.register(self._amqp_connection, alias)

    def _connect_to_http(self, host: str, port: Union[int, str], username: str, password: str, alias: str) -> int:
        """ Connect to server via HTTP.

        *Args*:\n
            _host_: server host name.\n
            _port_: port number.\n
            _username_: user name.\n
            _password_: user password.\n
            _alias_: connection alias.\n

        *Returns:*\n
            Server connection index.
        """
        if port is None:
            BuiltIn().fail(msg="RabbitMq: port for connect is None")
        port = int(port)
        timeout = 15
        parameters_for_connect = f"host={host}, port={port}, username={username}, timeout={timeout}, alias={alias}"

        logger.debug('Connecting using : {params}'.format(params=parameters_for_connect))
        try:
            self._http_connection = RequestConnection(host, port, username, password, timeout)
        except (gaierror, error, IOError):
            BuiltIn().fail(msg=f"RabbitMq: Could not connect with following parameters: {parameters_for_connect}")
        return self._http_cache.register(self._http_connection, alias)

    def create_rabbitmq_connection(self, host: str, http_port: Union[int, str], amqp_port: Union[int, str],
                                   username: str, password: str, alias: str, vhost: str) -> None:
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
        self._connect_to_http(host=host, port=http_port, username=username, password=password, alias=alias + "_http")
        self._connect_to_amqp(host=host, port=amqp_port, username=username, password=password, alias=alias + "_amqp",
                              virtual_host=vhost)

    def switch_rabbitmq_connection(self, alias: str) -> int:
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
        logger.debug(f'Switch active connection from {old_index} to {alias}')
        self._http_connection = self._http_cache.switch(alias + '_http')
        self._amqp_connection = self._amqp_cache.switch(alias + '_amqp')
        self._channel = None
        return old_index

    def disconnect_from_rabbitmq(self) -> None:
        """
        Close current RabbitMq connection.

        *Example:*\n
        | Create Rabbitmq Connection | my_host_name | 15672 | 5672 | guest | guest | alias=rmq |
        | Disconnect From Rabbitmq |
        """
        logger.debug(f'Close connection with : host={self.http_connection.host}, port={self.http_connection.port}')
        self.http_connection.close()
        self._http_connection = None
        self._channel = None
        if self._amqp_connection is not None:
            if self._amqp_connection.is_open:
                self._amqp_connection.close()
            self._amqp_connection = None

    def close_all_rabbitmq_connections(self) -> None:
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

    def _get_channel(self) -> BlockingChannel:
        """ Get channel from current connection.

        *Returns:*\n
            Channel.
        """
        if self._channel is None:
            self._channel = self.amqp_connection.channel()
        if self.amqp_connection.blocked:
            raise Exception('Connection is blocked')
        return self._channel

    def create_exchange(self, exchange_name: str, exchange_type: str, auto_delete: bool = False,
                        durable: bool = False, arguments: Dict[str, Any] = None) -> None:
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
        logger.debug(f"Creating new exchange {exchange_name} with type {exchange_type}")
        self._get_channel().exchange_declare(exchange=exchange_name,
                                             exchange_type=exchange_type,
                                             durable=durable,
                                             auto_delete=auto_delete,
                                             arguments=arguments)

    def is_exchange_exist(self, name: str, exchange_type: str) -> bool:
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
            self._get_channel().exchange_declare(exchange=name, exchange_type=exchange_type, passive=True)
            return True
        except ChannelClosed:
            return False

    def delete_exchange(self, exchange_name: str) -> None:
        """
        Delete exchange.

        *Args:*\n
        _exchange_name_ - exchange name;\n

        *Example:*\n
        | Delete Exchange | exchange_name=testExchange |
        """
        exchange_name = str(exchange_name)
        self._get_channel().exchange_delete(exchange=exchange_name)

    def create_queue(self, queue_name: str, auto_delete: bool = False, durable: bool = False,
                     node: str = None, arguments: Dict[str, Any] = None) -> None:
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
        self._get_channel().queue_declare(queue=queue_name, durable=durable, auto_delete=auto_delete,
                                          arguments=arguments)

    def is_queue_exist(self, name: str) -> bool:
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
        except ChannelClosed:
            return False

    def binding_exchange_with_queue(self, exchange_name: str, queue_name: str, routing_key: str = '',
                                    arguments: Dict[str, Any] = None) -> None:
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
        logger.debug(f'Binding queue {queue_name} to exchange {exchange_name}, with routing key {routing_key}')
        self._get_channel().queue_bind(queue=queue_name, exchange=exchange_name, routing_key=routing_key,
                                       arguments=arguments)

    def unbind_queue(self, queue_name: str, exchange_name: str, routing_key: str = '',
                     arguments: Dict[str, Any] = None) -> None:
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
        logger.debug(f'Unbind queue {queue_name} from exchange {exchange_name} with routing key {routing_key}')
        self._get_channel().queue_unbind(queue=queue_name, exchange=exchange_name, routing_key=routing_key,
                                         arguments=arguments)

    def purge_queue(self, queue_name: str) -> None:
        """
        Purge queue.

        *Args:*\n
        _queue_name_ - queue name;\n
        """
        queue_name = str(queue_name)
        logger.debug(f'Purge queue {queue_name}')
        self._get_channel().queue_purge(queue=queue_name)

    def delete_queue(self, queue_name: str) -> None:
        """
        Delete queue.

        *Args:*\n
        _queue_name_ - queue name;\n

        *Example:*\n
        | Delete Queue | queue_name=testQueue |
        """
        queue_name = str(queue_name)
        self._get_channel().queue_delete(queue=queue_name)

    def enable_consuming_messages_in_queue(self, queue_name: str, count: int, requeue: bool,
                                           consumed_list: List[int]) -> str:
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
        consumer_name = f"consumer{queue_name}"

        def on_message_callback(channel: BlockingChannel, method: Basic.Deliver, properties: BasicProperties,
                                body: bytes) -> None:
            """
            Callback for consuming messages from the queue.

            Processes specified number of messages and closes.

            *Args:*\n
                channel: BlockingChannel;
                method: spec.Basic.Deliver;
                properties: spec.BasicProperties;
                body: bytes.
            """
            tag = method.delivery_tag
            logger.debug(f"Consume message {tag} - {body}")
            channel.basic_reject(tag, requeue)
            consumed_list.append(tag)
            if len(consumed_list) >= count:
                channel.basic_cancel(consumer_name)

        logger.debug(f'Begin consuming messages. Queue={queue_name}, count={count}')
        self._get_channel().basic_consume(queue=queue_name, consumer_tag=consumer_name,
                                          on_message_callback=on_message_callback)
        return consumer_name

    def get_message_from_queue(self, queue_name: str, ack: bool = True) -> RabbitMqMessage:
        """Getting single message from RabbitMQ queue.
        Method gets first message from queue and acks it if ack=True.

        *Args:*\n
            queue_name: queue_name; \n
            ack: ack message or not (default=True);\n

        *Returns:*\n
            delivery_data: delivery_data dictionary.
            message_properties: message properties dictionary.
            body: message body.
            If queue is empty, returns None, None, None.

        *Example:*\n
        | Get Message From Queue | my_queue_name|
        """
        method, properties, body = self._get_channel().basic_get(
            queue=queue_name)

        if not (method and properties and body):
            return None, None, None
        else:
            delivery_data = {
                'delivery_tag': method.delivery_tag,
                'redelivered': method.redelivered,
                'exchange': method.exchange,
                'routing_key': method.routing_key,
                'message_count': method.message_count
            }

            message_properties = {
                'content_type': properties.content_type,
                'content_encoding': properties.content_encoding,
                'headers': properties.headers,
                'delivery_mode': properties.delivery_mode,
                'priority': properties.priority,
                'correlation_id': properties.correlation_id,
                'reply_to': properties.reply_to,
                'expiration': properties.expiration,
                'message_id': properties.message_id,
                'timestamp': properties.timestamp,
                'type': properties.type,
                'user_id': properties.user_id,
                'app_id': properties.app_id,
                'cluster_id': properties.cluster_id
            }
            if ack:
                delivery_tag = delivery_data['delivery_tag']
                self._get_channel().basic_ack(delivery_tag=delivery_tag)
            return delivery_data, message_properties, body

    def publish_message(self, exchange_name: str, routing_key: str, payload: str, props: Dict[str, Any] = None) -> None:
        """
        Publish message to the queue.

        *Args:*\n
        _exchange_name_ - exchange name;\n
        _routing_key_ - routing key (quoted with requests.utils.quote);\n
        _payload_ - payload message;\n
        _props_ - additional arguments in dictionary format;\n
         Includes such keys as:\n
        - _content_type_ - message content type (shortstr);
        - _content_encoding_ - message encoding type (shortstr);
        - _headers_ - message headers table, a dictionary with keys of type string and values of types
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
        | ${prop_dict}= | Create Dictionary | application_headers=${headers_dict} | content_type=text/plain | priority=1 | expiration=1410966000 | message_id=101 | user_id=guest |
        | Publish Message | exchange_name=testExchange | routing_key=testQueue | payload=message body | props=${prop_dict} |
        """
        if props is not None:
            props = pika.BasicProperties(**props)
        exchange_name = str(exchange_name)
        routing_key = str(routing_key)
        logger.debug(f'Publish message to {exchange_name} with routing {routing_key}')
        self._get_channel().basic_publish(exchange=exchange_name, routing_key=routing_key,
                                          body=payload, properties=props)

    def process_published_message_in_queries(self, waiting: int = 1) -> None:
        """
        Send processing of published message in queues to handler.\n
        May end with exception if handler is not installed or there are no messages in queue.\n

        *Args:*\n
        _waiting_ - server response timeout.
        """
        waiting = int(waiting)
        self.amqp_connection.process_data_events(time_limit=waiting)

    def enable_message_sending_confirmation(self, confirmed_list: List[str], activate: bool = True) -> None:
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
        def confirm_callback(method: FrameMethod) -> None:
            """
            Called when sending message notification is received.
            """
            delivery_tag = method.method.delivery_tag
            logger.debug(f'Capture confirm message with tag={delivery_tag}')
            confirmed_list.append(delivery_tag)

        self._get_channel().confirm_delivery()
        logger.debug('Begin checking confirm publish')
        if activate is True:
            self._get_channel()._impl.add_callback(callback=confirm_callback,
                                                   replies=[pika.spec.Basic.Ack],
                                                   one_shot=False)

    # Manager API

    @staticmethod
    def _prepare_request_headers(body: Dict[str, Any] = None) -> Dict[str, str]:
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
    def _quote_vhost(vhost: str) -> str:
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

    def is_alive(self) -> bool:
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
            response = requests.get(self.http_connection.url,
                                    auth=self.http_connection.auth,
                                    headers=self._prepare_request_headers(),
                                    timeout=self.http_connection.timeout)
        except requests.exceptions.RequestException as e:
            raise Exception(f'Could not send request: {e}')
        logger.debug(f'Response status={response.status_code}')
        return response.status_code == 200

    def overview(self) -> Dict[str, Any]:
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
        | contexts | [{'node': 'rabbit@primary', 'path': '/', 'description': 'RabbitMQ Management', 'port': 15672}, {'node': 'rabbit@primary', 'path': '/web-stomp-examples', 'description': 'WEB-STOMP: examples', 'port': 15670}] |
        | erlang_full_version | Erlang R16B03 (erts-5.10.4) [source] [64-bit] [async-threads:30] [kernel-poll:true] |
        | erlang_version | R16B03 |
        | exchange_types | [{'enabled': True, 'name': 'fanout', 'description': 'AMQP fanout exchange, as per the AMQP specification'}, {'internal_purpose': 'federation', 'enabled': True, 'name': 'x-federation-upstream', 'description': 'Federation upstream helper exchange'}, {'enabled': True, 'name': 'direct', 'description': 'AMQP direct exchange, as per the AMQP specification'}, {'enabled': True, 'name': 'headers', 'description': 'AMQP headers exchange, as per the AMQP specification'}, {'enabled': True, 'name': 'topic', 'description': 'AMQP topic exchange, as per the AMQP specification'}, {'enabled': True, 'name': 'x-consistent-hash', 'description': 'Consistent Hashing Exchange'}] |
        | listeners | [{'node': 'rabbit@primary', 'ip_address': '::', 'protocol': 'amqp', 'port': 5672}, {'node': 'rabbit@primary', 'ip_address': '::', 'protocol': 'clustering', 'port': 25672}, {'node': 'rabbit@primary', 'ip_address': '::', 'protocol': 'mqtt', 'port': 1883}, {'node': 'rabbit@primary', 'ip_address': '::', 'protocol': 'stomp', 'port': 61613}] |
        | management_version | 3.3.0 |
        | message_stats | {'publish_details': {'rate': 0.0}, 'confirm': 85, 'deliver_get': 85, 'publish': 85, 'confirm_details': {'rate': 0.0}, 'get_no_ack': 85, 'get_no_ack_details': {'rate': 0.0}, 'deliver_get_details': {'rate': 0.0}} |
        | node | rabbit@primary |
        | object_totals | {'connections': 0, 'channels': 0, 'queues': 2, 'consumers': 0, 'exchanges': 10} |
        | queue_totals | {'messages_details': {'rate': 0.0}, 'messages': 0, 'messages_ready': 0, 'messages_ready_details': {'rate': 0.0}, 'messages_unacknowledged': 0, 'messages_unacknowledged_details': {'rate': 0.0}} |
        | rabbitmq_version | 3.3.0 |
        | statistics_db_node | rabbit@primary |
        | statistics_level | fine |

        ${version} = 3.3.0
        """
        url = self.http_connection.url + '/overview'
        response = requests.get(url, auth=self.http_connection.auth,
                                headers=self._prepare_request_headers(),
                                timeout=self.http_connection.timeout)
        response.raise_for_status()
        return response.json()

    def connections(self) -> List[Dict[str, Any]]:
        """ List of open connections.

        *Returns:*\n
            List of open connections in JSON format.

        *Raises:*\n
            raise HTTPError if the HTTP request returned an unsuccessful status code.
        """
        url = self.http_connection.url + '/connections'
        response = requests.get(url, auth=self.http_connection.auth,
                                headers=self._prepare_request_headers(),
                                timeout=self.http_connection.timeout)
        response.raise_for_status()
        return response.json()

    def get_name_of_all_connections(self) -> List[str]:
        """ List with names of all open connections.

        *Returns:*\n
            List with names of all open connections.
        """
        return [item['name'] for item in self.connections()]

    def channels(self) -> List[Dict[str, Any]]:
        """ List of open channels.

        *Returns:*\n
             List of open channels in JSON format.
        *Raises:*\n
            raise HTTPError if the HTTP request returned an unsuccessful status code.
        """
        url = self.http_connection.url + '/channels'
        response = requests.get(url, auth=self.http_connection.auth,
                                headers=self._prepare_request_headers(),
                                timeout=self.http_connection.timeout)
        response.raise_for_status()
        return response.json()

    def get_exchange(self, exchange_name: str, vhost: str = '%2F') -> Dict[str, Any]:
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
        path = f'/exchanges/{self._quote_vhost(vhost)}/{quote(exchange_name)}'
        response = requests.get(self.http_connection.url + path,
                                auth=self.http_connection.auth,
                                headers=self._prepare_request_headers(),
                                timeout=self.http_connection.timeout)
        response.raise_for_status()
        return response.json()

    def exchanges(self) -> List[Dict[str, Any]]:
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
        | 0 | {'name': '', 'durable': True, 'vhost': '/', 'internal': False, 'message_stats': [], 'arguments': {}, 'type': 'direct', 'auto_delete': False} |
        | 1 | {'name': 'amq.direct', 'durable': True, 'vhost': '/', 'internal': False, 'message_stats': [], 'arguments': {}, 'type': 'direct', 'auto_delete': False} |
        ...\n
        ${name} = amq.direct
        """
        url = self.http_connection.url + '/exchanges'
        response = requests.get(url, auth=self.http_connection.auth,
                                headers=self._prepare_request_headers(),
                                timeout=self.http_connection.timeout)
        response.raise_for_status()
        return response.json()

    def get_names_of_all_exchanges(self) -> List[str]:
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

    def get_exchanges_on_vhost(self, vhost: str = '%2F') -> List[Dict[str, Any]]:
        """ List of exchanges on virtual host.

        *Returns:*\n
            List of exchanges in JSON format.

        *Raises:*\n
            raise HTTPError if the HTTP request returned an unsuccessful status code.

        *Args:*\n
        _vhost_ - virtual host name (quoted with requests.utils.quote);
        """
        url = self.http_connection.url + '/exchanges/' + self._quote_vhost(vhost)
        response = requests.get(url, auth=self.http_connection.auth,
                                headers=self._prepare_request_headers(),
                                timeout=self.http_connection.timeout)
        response.raise_for_status()
        return response.json()

    def get_names_of_exchanges_on_vhost(self, vhost: str = '%2F') -> List[str]:
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

    def get_queue(self, queue_name: str, vhost: str = '%2F') -> Dict[str, Any]:
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
        path = f'/queues/{self._quote_vhost(vhost)}/{quote(queue_name)}'
        response = requests.get(self.http_connection.url + path,
                                auth=self.http_connection.auth,
                                headers=self._prepare_request_headers(),
                                timeout=self.http_connection.timeout)
        response.raise_for_status()
        return response.json()

    def queues(self) -> List[Dict[str, Any]]:
        """ List of queues.

        *Returns:*\n
            List of queues in JSON format.

        *Raises:*\n
            raise HTTPError if the HTTP request returned an unsuccessful status code.
        """
        url = self.http_connection.url + '/queues'
        response = requests.get(url, auth=self.http_connection.auth,
                                headers=self._prepare_request_headers(),
                                timeout=self.http_connection.timeout)
        response.raise_for_status()
        return response.json()

    def get_queues_on_vhost(self, vhost: str = '%2F') -> List[Dict[str, Any]]:
        """ List of queues on virtual host.

        *Args:*\n
        _vhost_ - virtual host name (quoted with requests.utils.quote);\n

        *Returns:*\n
            List of queues in JSON format.

        *Raises:*\n
            raise HTTPError if the HTTP request returned an unsuccessful status code.
        """
        url = self.http_connection.url + '/queues/' + self._quote_vhost(vhost)
        response = requests.get(url, auth=self.http_connection.auth,
                                headers=self._prepare_request_headers(),
                                timeout=self.http_connection.timeout)
        response.raise_for_status()
        return response.json()

    def get_names_of_queues_on_vhost(self, vhost: str = '%2F') -> List[str]:
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

    def get_binding_exchange_with_queue_list(self, exchange_name: str, queue_name: str,
                                             vhost: str = '%2F') -> List[Dict[str, Any]]:
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
        | arguments | {'arg1': 'value1', 'arg2': ['str1', False]} |
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

        response = requests.get(self.http_connection.url + path,
                                auth=self.http_connection.auth,
                                headers=self._prepare_request_headers(),
                                timeout=self.http_connection.timeout)
        response.raise_for_status()
        return response.json()

    def get_message(self, queue_name: str, count: int, requeue: bool, encoding: str, truncate: int = None,
                    vhost: str = '%2F', ackmode: str = 'ack_requeue_true') -> List[Dict[str, Any]]:
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
        | 0 | {'payload': 'message body 0', 'exchange': 'testExchange', 'routing_key': 'testQueue', 'payload_bytes': 14, 'message_count': 4, 'payload_encoding': 'string', 'redelivered': False, 'properties': []} |
        | 1 | {'payload': 'message body 1', 'exchange': 'testExchange', 'routing_key': 'testQueue', 'payload_bytes': 14, 'message_count': 3, 'payload_encoding': 'string', 'redelivered': False, 'properties': []} |
        | ... |
        """
        path = f'/queues/{self._quote_vhost(vhost)}/{quote(queue_name)}/get'
        body = {"count": count, "requeue": requeue, "encoding": encoding, "ackmode": ackmode}
        if truncate is not None:
            body["truncate"] = truncate
        response = requests.post(self.http_connection.url + path,
                                 auth=self.http_connection.auth,
                                 headers=self._prepare_request_headers(body=body),
                                 data=json.dumps(body),
                                 timeout=self.http_connection.timeout)
        response.raise_for_status()
        return response.json()

    def vhosts(self) -> List[Dict[str, Any]]:
        """ List of virtual hosts.
        *Returns:*\n
            List of virtual hosts in JSON format.

        *Raises:*\n
            raise HTTPError if the HTTP request returned an unsuccessful status code.
        """
        url = self.http_connection.url + '/vhosts'
        response = requests.get(url, auth=self.http_connection.auth,
                                headers=self._prepare_request_headers(),
                                timeout=self.http_connection.timeout)
        response.raise_for_status()
        return response.json()

    def nodes(self) -> List[Dict[str, Any]]:
        """ List of nodes.

        *Returns:*\n
            List of nodes in JSON format.

        *Raises:*\n
            raise HTTPError if the HTTP request returned an unsuccessful status code.
        """
        url = self.http_connection.url + '/nodes'
        response = requests.get(url, auth=self.http_connection.auth,
                                headers=self._prepare_request_headers(),
                                timeout=self.http_connection.timeout)
        response.raise_for_status()
        return response.json()

    def _cluster_name(self) -> List[Dict[str, Any]]:
        """ List of clusters.

        *Returns:*\n
            List of clusters in JSON format.

        *Raises:*\n
            raise HTTPError if the HTTP request returned an unsuccessful status code.
        """
        url = self.http_connection.url + '/cluster-name'
        response = requests.get(url, auth=self.http_connection.auth,
                                headers=self._prepare_request_headers(),
                                timeout=self.http_connection.timeout)
        response.raise_for_status()
        return response.json()
