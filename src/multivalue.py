from typing import Callable, Tuple, TypeVar, final, Iterable, Iterator, Generator

from returns.interfaces.bindable  import Bindable1
from returns.interfaces.mappable  import Mappable1
from returns.interfaces.container import Container1
from returns.primitives.container import BaseContainer, container_equality
from returns.primitives.hkt       import SupportsKind1, Kind1
from returns.interfaces.equable   import Equable

_FirstType     = TypeVar('_FirstType')
_NewFirstType  = TypeVar('_NewFirstType')

@final
class MIterator(
    Iterable,
    Bindable1,
    Mappable1,
    BaseContainer,
    SupportsKind1['MIterator', _FirstType],
):
    def __init__(
        self,
        iterable: Iterable[_FirstType]
    ) -> None:
        """initialize from an iterable"""
        super().__init__(iter(iterable))

    # 'Mappable' part:
    def map(
        self,
        function: Callable[[_FirstType], _NewFirstType],
    ) -> 'MIterator[_NewFirstType]':
        """
        Map the inner values to new ones

        >>> list(MIterator.from_value().map(lambda x : x + 1))
        []
        >>> list(MIterator.from_value(1, 2, 3, 4, 5).map(lambda x : x + 1))
        [2, 3, 4, 5, 6]

        """
        return  MIterator((function(v) for v in self))

    # 'BindableN' part:
    def bind(
        self,
        function: Callable[[_FirstType], 'MIterator[_NewFirstType]']
    ) -> 'MIterator[_NewFirstType]':
        """
        Changes the values with a function returning another MIterator

        >>> empty = lambda _ : MIterator.from_value()
        >>> list(MIterator.from_value(0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10).bind(empty))
        []
        >>> f = lambda n : MIterator.from_value(n + 1, n + 2, n + 3)
        >>> list(MIterator.from_value(10, 20, 30).bind(f))
        [11, 12, 13, 21, 22, 23, 31, 32, 33]

        """
        return MIterator(
            it1
            for it0 in self.map(function)
            for it1 in it0
        )

    def filter(
        self,
        function: Callable[[_FirstType], bool]
    ) -> 'MIterator[_NewFirstType]':
        """
        Filter the values based on the bool of function(_NewFirstType)
        >>> list(MIterator(range(10)).filter(lambda x : x > 3))
        [4, 5, 6, 7, 8, 9]
        """
        return MIterator(filter(function, self))

    # iterator part:
    def __next__(self):
        """imitate an iterator, produce values lazily
        >>> lst = MIterator.from_value(0, 1, 2, 3)
        >>> next(lst)
        0
        >>> next(lst)
        1
        >>> next(lst)
        2
        >>> next(lst)
        3
        """
        return next(self._inner_value)

    def __iter__(self) -> Kind1['MIterator', _FirstType]:
        """imitate an iterator, produce values lazily
        >>> list(MIterator.from_value())
        []
        >>> lst = MIterator.from_value(0, 1, 2, 3)
        >>> list(lst)
        [0, 1, 2, 3]
        """
        return self

    @classmethod
    def from_value(
        cls,
        *values: Iterable[_FirstType]
    ) -> Kind1['MIterator', _FirstType]:
        """Saves multiple values in an iterator and produce them lazily"""
        return MIterator(iter(values))

    @classmethod
    def do(
        cls,
        expr: Iterable[_NewFirstType],
    ) -> 'MIterator[_NewFirstType]':
        """
        Allows working with diffent amount value of containers in a safe way.

        .. code:: python
          >>> from multivalue import MIterator
          >>> assert list(MIterator.do(
          ...     first + second
          ...     for first  in MIterator.from_value(1, 2, 3)
          ...     for second in MIterator.from_value(3)
          ... )) == list(MIterator.from_value(4, 5, 6))

        See :ref:`do-notation` to learn more.
        """
        return MIterator(expr)

    @classmethod
    def from_multivalue(
        cls,
        multivalue: Kind1['MultiValue', _FirstType]
    ) -> Kind1['MIterator', _FirstType]:
        return MIterator(iter(multivalue))



@final
class MultiValue(
    Iterable,
    Container1,
    Equable,
    BaseContainer,
    SupportsKind1['MultiValue', _FirstType],
):
    def __init__(
        self,
        *args: Iterable[_FirstType]
    ) -> None:
        """initialize from args list"""
        super().__init__(args)

    # 'Mappable' part:
    def map(
        self,
        function: Callable[[_FirstType], _NewFirstType],
    ) -> 'MultiValue[_NewFirstType]':
        """
        Map the inner values to new ones

        >>> list(MultiValue().map(lambda x : x + 1))
        []
        >>> list(MultiValue(1, 2, 3, 4, 5).map(lambda x : x + 1))
        [2, 3, 4, 5, 6]

        """
        return  MultiValue(*(function(i) for i in self._inner_value))

    # 'BindableN' part:
    def bind(
        self,
        function: Callable[[_FirstType], 'MultiValue[_NewFirstType]']
    ) -> 'MultiValue[_NewFirstType]':
        """
        Changes the values with a function returning another MultiValue

        >>> empty = lambda _ : MultiValue()
        >>> list(MultiValue(0, 1, 2, 3, 4, 5, 6, 7, 8, 9, 10).bind(empty))
        []
        >>> f = lambda n : MultiValue(n + 1, n + 2, n + 3)
        >>> list(MultiValue(10, 20, 30).bind(f))
        [11, 12, 13, 21, 22, 23, 31, 32, 33]

        """
        return MultiValue(*(
            it1
            for it0 in self.map(function)
            for it1 in it0
        ))

    # 'AppliableN' part:
    def apply(
        self,
        contain_func: Kind1['MultiValue', _FirstType]
    ) ->Kind1['MultiValue', _FirstType]:
        return MultiValue(*(
            f(v)
            for f in contain_func
            for v in self
        ))

    @classmethod
    def from_iter(
        cls,
        iter: Iterable[_FirstType]
    ) -> Kind1['MultiValue', _FirstType]:
        """Saves multiple values in an tuple"""
        return MultiValue(*iter)


    @classmethod
    def do(
        cls,
        expr: Iterable[_NewFirstType],
    ) -> 'MultiValue[_NewFirstType]':
        """
        Allows working with unwrapped values of containers in a safe way.

        .. code:: python
          >>> from multivalue import MultiValue
          >>> assert MultiValue.do(
          ...     first + second
          ...     for first in MultiValue(1, 2, 3)
          ...     for second in MultiValue(3)
          ... ) == MultiValue(4, 5, 6)

        See :ref:`do-notation` to learn more.
        """
        return MultiValue(*expr)

    # `Equable` part:
    equals = container_equality  # we already have this defined for all types

    def __iter__(self) -> Kind1['MultiValue', _FirstType]:
        """imitate an iterator, produce values lazily
        >>> list(MultiValue())
        []
        >>> list(MultiValue(0, 1, 2, 3))
        [0, 1, 2, 3]
        """
        return iter(self._inner_value)

