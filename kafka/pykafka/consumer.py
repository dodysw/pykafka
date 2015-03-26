import itertools
from collections import defaultdict
from Queue import Queue, Empty

from kafka import base
from kafka.common import OffsetType

from .protocol import PartitionFetchRequest

# Settings to add to the eventual BalancedConsumer
# consumer_group
# rebalance_max_retries
# rebalance_backoff_ms
# partition_assignment_strategy


class SimpleConsumer(base.BaseSimpleConsumer):

    def __init__(self,
                 topic,
                 client_id=None,
                 consumer_group=None,
                 partitions=None,
                 socket_timout_ms=30000,
                 socket_receive_buffer_bytes=60 * 1024,
                 fetch_message_max_bytes=1024 * 1024,
                 num_consumer_fetchers=1,
                 auto_commit_enable=False,
                 auto_commit_interval_ms=60 * 1000,
                 queued_max_message_chunks=2,
                 fetch_min_bytes=1,
                 fetch_wait_max_ms=100,
                 refresh_leader_backoff_ms=200,
                 offsets_channel_backoff_ms=1000,
                 offsets_channel_socket_timeout_ms=10000,
                 offsets_commit_max_retries=5,
                 auto_offset_reset=OffsetType.LATEST,
                 consumer_timeout_ms=-1):
        """Create a SimpleConsumer.

        Settings and default values are taken from the Scala
        consumer implementation.  Consumer group is included
        because it's necessary for offset management, but doesn't imply
        that this is a balancing consumer. Use a BalancedConsumer for
        that.

        TODO: param docs
        """
        self._consumer_group = consumer_group
        self._topic = topic
        self._fetch_message_max_bytes = fetch_message_max_bytes
        self._auto_commit_enable = auto_commit_enable
        self._auto_commit_interval_ms = auto_commit_interval_ms

        if partitions:
            self._partitions = {OwnedPartition(p, self): topic.partitons[p]
                                for p in partitions}
        else:
            self._partitons = {OwnedPartition(p, self): p
                               for p in topic.partitions}
        # Organize partitions by leader for efficient queries
        self._partitions_by_leader = defaultdict(list)
        for p in self._partitions.itervalues():
            self._partitions_by_leader[p.leader] = p
        self.partition_cycle = itertools.cycle(self._partitions().keys())

    @property
    def topic(self):
        return self._topic

    @property
    def partitions(self):
        return self._partitions

    @property
    def fetch_message_max_bytes(self):
        return self._fetch_message_max_bytes

    def __iter__(self):
        while True:
            yield self.consume()

    def consume(self, timeout=None):
        """Get one message from the consumer.

        :param timeout: Seconds to wait before returning None
        """
        owned_partition = self.partition_cycle.next()
        message = owned_partition.consume(timeout=timeout)

        if self._auto_commit_enable:
            self._auto_commit()

        return message

    def _auto_commit(self):
        pass

    def commit_offsets(self):
        """Use the Offset Commit/Fetch API to commit offsets for this
            consumer's topic
        """
        pass

    def fetch_offsets(self):
        """Use the Offset Commit/Fetch API to fetch offsets for this
            consumer's topic
        """
        pass


class OwnedPartition(object):
    """A partition that is owned by a SimpleConsumer.

    Used to keep track of offsets and the internal message queue.
    """

    def __init__(self, partition, consumer):
        self.partition = partition
        self.consumer = consumer
        self._messages = Queue()
        self.last_offset_consumed = 0
        self.next_offset = 0

        if self.consumer._auto_commit_enable and self.consumer.consumer_group is not None:
            self.last_offset_consumed = self._fetch_last_known_offset()

    def consume(self, timeout=None):
        """Get a single message from this partition
        """
        if self._messages.empty():
            self._fetch()

        try:
            message = self._messages.get_nowait()
            self.last_offset_consumed = message.offset
            return message
        except Empty:
            return None

    def _fetch_last_known_offset(self):
        """Use the Offset Commit/Fetch API to find the last known offset for
            this partition
        """
        pass

    def _fetch(self):
        topic_name = self.partition.topic.name
        success = False
        while success is False:
            try:
                request = PartitionFetchRequest(
                    self.partition.topic.name, self.partition.id, self.next_offset,
                    self.consumer.fetch_message_max_bytes
                )

                response = self.partition.leader.fetch_messages(request)

                for message in response.topics[topic_name].messages:
                    if message.offset < self.last_offset_consumed:
                        continue

                    self._messages.put(message)
                    self.next_offset = message.offset + 1
                success = True
            except:
                success = False
