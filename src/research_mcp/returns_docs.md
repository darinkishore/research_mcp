
# Returns Library Documentation

Welcome to the **Returns** library documentation! This guide provides a comprehensive overview of the Returns library, a powerful tool for functional programming in Python. Whether you're integrating it into a new project or enhancing an existing one, Returns offers flexible and type-safe abstractions to streamline your development process.

## Quickstart

### Basic Usage

Here's a simple example using the `Result` container to handle potential errors without using exceptions:

```python
from returns.result import Result, Success, Failure

def divide(dividend: int, divisor: int) -> Result[float, str]:
    if divisor == 0:
        return Failure("Cannot divide by zero.")
    return Success(dividend / divisor)

result = divide(10, 2)
print(result)  # <Success: 5.0>

result = divide(10, 0)
print(result)  # <Failure: Cannot divide by zero.>
```

### Chaining Operations

You can chain multiple operations using `map` and `bind` to handle transformations and dependencies seamlessly:

```python
from returns.result import Result, Success, Failure

def to_int(value: str) -> Result[int, str]:
    try:
        return Success(int(value))
    except ValueError:
        return Failure("Invalid integer.")

def reciprocal(value: int) -> Result[float, str]:
    if value == 0:
        return Failure("Cannot take reciprocal of zero.")
    return Success(1 / value)

result = Success("10").bind(to_int).bind(reciprocal)
print(result)  # <Success: 0.1>

result = Success("0").bind(to_int).bind(reciprocal)
print(result)  # <Failure: Cannot take reciprocal of zero.>

result = Success("abc").bind(to_int).bind(reciprocal)
print(result)  # <Failure: Invalid integer.>
```

---

## Why Use Returns?

One of the most common questions among Python developers is: **Why would we need Returns?**

**Returns** provides functional programming abstractions that address common challenges in a type-safe manner:

- **Handling `None` Values:** Use `Maybe` to work with optional values without the pitfalls of `None`.
- **Exception Management:** Use `Result` to handle exceptions type-safely.
- **Separating Pure and Impure Code:** Use `IO` to distinguish between pure and impure parts of your codebase.
- **Asynchronous Code:** Use `Future` to write asynchronous code without explicit `await` statements.
- **Dependency Injection:** Use `RequiresContext` to inject dependencies in a readable and type-safe way.
- **Data Pipelines:** Use `Pipelines` to create complex, declarative, and type-safe data flows.

Additionally, Returns offers interfaces that allow you to switch implementations on the fly, supporting both synchronous and asynchronous execution flows while maintaining type safety. You can also extend the library by writing your own primitives based on existing or custom interfaces.

In essence, **Returns** empowers Python developers with the capabilities of typed functional programming, enhancing code reliability and maintainability.

---

## Containers

### Concept

A **Container** in Returns is an abstraction that wraps values while preserving the execution context. This allows you to build complex data flows and handle various scenarios like optional values, errors, and side effects in a structured way.

#### Supported Containers

- **Maybe:** Handles optional values (`None` cases).
- **Result:** Manages operations that can succeed or fail.
- **IO:** Marks explicit IO actions.
- **Future:** Facilitates asynchronous programming without `await`.
- **RequiresContext:** Injects dependencies in a type-safe manner.
- **Combinations:** `IOResult`, `FutureResult`, `RequiresContextResult`, `RequiresContextIOResult`, and `RequiresContextFutureResult`.

### Basics

The core idea behind a container is that it encapsulates an internal state, accessible via the `.inner_value` attribute. Containers provide functions to create new containers based on the current state, allowing you to observe how the state evolves during execution.

#### State Evolution Example

```python
from returns.result import Result, Success, Failure

initial = Result.from_value(1)  # <Success: 1>
user_id = Result.from_value(UserId(1))  # <Success: UserId(1)>
account = Result.from_value(UserAccount(156))  # <Success: UserAccount(156)>
failed_attempt = Result.from_failure(FailedLoginAttempt(1))  # <Failure: FailedLoginAttempt(1)>
notification = Result.from_value(SentNotificationId(992))  # <Success: SentNotificationId(992)>
```

### Working with a Container

Containers provide two primary methods for creating new containers from existing ones: `map` and `bind`.

- **`map`** applies a function to the wrapped value, returning a new container with the transformed value.
- **`bind`** applies a function that returns a new container, effectively chaining operations.

#### `map` Example

```python
from returns.result import Success

def double(state: int) -> int:
    return state * 2

result: Result[int, str] = Success(1).map(double)
print(result)  # <Success: 2>

result = result.map(lambda state: state + 1)
print(result)  # <Success: 3>
```

#### `bind` Example

```python
from returns.result import Result, Success

def may_fail(user_id: int) -> Result[float, str]:
    if user_id > 0:
        return Success(1.0 / user_id)
    return Failure("Invalid user ID.")

value: Result[int, str] = Success(1)
result: Result[float, str] = value.bind(may_fail)
print(result)  # <Success: 1.0>
```

**Note:** All containers support `map` and `bind` methods as they implement `MappableN` and `BindableN` interfaces.

### Instantiating a Container

Containers can be instantiated using the `.from_value` method provided by the `ApplicativeN` interface.

#### Example

```python
from returns.result import Result

success = Result.from_value(1)
print(success)  # <Success: 1>
```

#### Other Constructors

- **Maybe:**

    ```python
    from returns.maybe import Maybe, Some, Nothing

    some_value = Maybe.from_optional(1)
    print(some_value)  # <Some: 1>

    none_value = Maybe.from_optional(None)
    print(none_value)  # <Nothing>
    ```

- **Failure:**

    ```python
    from returns.result import Result, Failure

    failure = Result.from_failure("Error occurred")
    print(failure)  # <Failure: Error occurred>
    ```

### Immutability

Returns containers are designed to be immutable. Attempts to mutate the inner state will fail because the containers override `__setattr__` and `__delattr__` and use `__slots__` for performance and strictness. While Python doesn't enforce true immutability, Returns ensures that container instances remain immutable within their design constraints.

For additional immutability guarantees, use the `Immutable` mixin:

```python
from returns.primitives.types import Immutable

class MyClass(Immutable):
    def __init__(self, value: int):
        self.value = value
```

### Type Safety

Returns enhances type safety through optional type annotations. When using type checkers like `mypy`, Returns containers provide precise type information, helping catch type-related errors at development time.

#### Type Annotations Example

```python
from returns.result import Result, Success

def callback(arg: int) -> Result[float, int]:
    return Success(float(arg))

first: Result[int, int] = Success(1)
result = first.bind(callback)
print(result)  # <Success: 1.0>
```

**Note:** Returns ships PEP 561 compatible `.pyi` files and custom `mypy` plugins to improve type-checking capabilities. Ensure you configure `mypy` to use these plugins for the best type safety experience.

---

## Working with Multiple Containers

### Multiple Container Arguments

When dealing with functions that accept multiple arguments and multiple containers, Returns provides tools like partial application and the `.apply()` method to compose them effectively.

#### Example

```python
from returns.curry import curry
from returns.io import IO

@curry
def sum_two_numbers(first: int, second: int) -> int:
    return first + second

one = IO(1)
two = IO(2)

result = two.apply(one.apply(IO(sum_two_numbers)))
print(result)  # IO(3)
```

Alternatively, using `partial`:

```python
from returns.curry import partial

result = two.apply(
    one.apply(
        IO(lambda x: partial(sum_two_numbers, x))
    )
)
print(result)  # IO(3)
```

Or using lambda functions:

```python
result = two.apply(
    one.apply(
        IO(lambda x: lambda y: sum_two_numbers(x, y))
    )
)
print(result)  # IO(3)
```

### Working with Iterable of Containers

Returns provides the `Fold` utility to handle iterables of containers, enabling operations like folding and collecting.

#### Summing an Iterable of `IO` Containers

```python
from typing import Callable
from returns.io import IO
from returns.iterables import Fold

def sum_two_numbers(first: int) -> Callable[[int], int]:
    return lambda second: first + second

numbers = [IO(2) for _ in range(10)]

result = Fold.loop(
    numbers,
    IO(0),
    sum_two_numbers,
)
print(result)  # IO(20)
```

#### Collecting an Iterable of Containers

```python
from typing import List
from returns.maybe import Maybe, Some, Nothing, maybe
from returns.iterables import Fold

source = {'a': 1, 'b': 2}

fetched_values: List[Maybe[int]] = [
    maybe(source.get)(key)
    for key in ('a', 'b')
]

collected = Fold.collect(fetched_values, Some(()))
print(collected)  # Some((1, 2))

# Handling missing keys
fetched_values = [
    maybe(source.get)(key)
    for key in ('a', 'c')  # 'c' is missing!
]

collected = Fold.collect(fetched_values, Some(()))
print(collected)  # Nothing
```

**Note:** `Fold.collect_all` can be used to collect all successful values even if some fail.

---

## Railway Oriented Programming

### Error Handling

Returns implements **Railway Oriented Programming (ROP)**, a paradigm where program flow has two tracks:

- **Success Track:** All operations succeed.
- **Failure Track:** Any operation fails.

You can seamlessly switch between these tracks using methods like `bind`, `map`, `alt`, and `lash`.

#### Example Workflow

```
Success --> bind --> Success --> bind --> Failure --> lash --> Success
```

### Returning Execution to the Right Track

Returns provides methods to handle and transform failures:

- **`alt`**: Transforms the error in a failed container.
- **`lash`**: Chains operations on failed containers, allowing recovery.

#### `alt` Example

```python
from returns.result import Failure

transformed = Failure(1).alt(str)
print(transformed)  # <Failure: '1'>
```

#### `lash` Example

```python
from returns.result import Result, Failure, Success

def tolerate_exception(state: Exception) -> Result[int, Exception]:
    if isinstance(state, ZeroDivisionError):
        return Success(0)
    return Failure(state)

value: Result[int, Exception] = Failure(ZeroDivisionError())
result = value.lash(tolerate_exception)
print(result)  # <Success: 0>

value2: Result[int, Exception] = Failure(ValueError())
result2 = value2.lash(tolerate_exception)
print(result2)  # <Failure: ValueError()>
```

**Note:** Not all containers support `alt` and `lash`. Only those implementing `AltableN` and `LashableN` interfaces do.

---

## Containers Overview

### Maybe

The `Maybe` container represents optional values, encapsulating the presence (`Some`) or absence (`Nothing`) of a value.

#### Creation

```python
from returns.maybe import Maybe, Some, Nothing

some_value = Maybe.from_optional(1)
print(some_value)  # <Some: 1>

none_value = Maybe.from_optional(None)
print(none_value)  # <Nothing>
```

#### Usage Example

```python
from dataclasses import dataclass
from typing import Optional
from returns.maybe import Maybe, Nothing

@dataclass
class Address:
    street: Optional[str]

@dataclass
class User:
    address: Optional[Address]

@dataclass
class Order:
    user: Optional[User]

def get_street_address(order: Order) -> Maybe[str]:
    return Maybe.from_optional(order.user).bind_optional(
        lambda user: user.address,
    ).bind_optional(
        lambda address: address.street,
    )

with_address = Order(User(Address('Some street')))
empty_user = Order(None)
empty_address = Order(User(None))
empty_street = Order(User(Address(None)))

print(get_street_address(with_address))  # <Some: Some street>
print(get_street_address(empty_user))    # <Nothing>
print(get_street_address(empty_address)) # <Nothing>
print(get_street_address(empty_street))  # <Nothing>
```

#### Pattern Matching

```python
from dataclasses import dataclass
from typing import Final
from returns.maybe import Maybe, Nothing, Some

@dataclass
class Book:
    book_id: int
    name: str

_BOOK_LIST: Final = (
    Book(book_id=1, name='Category Theory for Programmers'),
    Book(book_id=2, name='Fluent Python'),
    Book(book_id=3, name='Learn You Some Erlang for Great Good'),
    Book(book_id=4, name='Learn You a Haskell for Great Good'),
)

def find_book(book_id: int) -> Maybe[Book]:
    for book in _BOOK_LIST:
        if book.book_id == book_id:
            return Some(book)
    return Nothing

desired_book = find_book(2)
match desired_book:
    case Some(Book(name='Fluent Python')):
        print('"Fluent Python" was found')
    case Some(book):
        print(f'Book found: {book.name}')
    case Maybe.empty:
        print('Book not found!')
```

#### FAQ: Modeling Absence vs. Presence of `None`

```python
from typing import Dict, Optional, TypeVar
from returns.maybe import Maybe, Some, Nothing

_Key = TypeVar('_Key')
_Value = TypeVar('_Value')

def check_key(
    haystack: Dict[_Key, _Value],
    needle: _Key,
) -> Maybe[_Value]:
    if needle not in haystack:
        return Nothing
    return Maybe.from_value(haystack[needle])  # Use `.from_optional` if needed

real_values = {'a': 1}
opt_values = {'a': 1, 'b': None}

print(check_key(real_values, 'a'))  # <Some: 1>
print(check_key(real_values, 'b'))  # <Nothing>
print(check_key(opt_values, 'a'))    # <Some: 1>
print(check_key(opt_values, 'b'))    # <Some: None>
print(check_key(opt_values, 'c'))    # <Nothing>
```

**Note:** `Some(None)` is distinct from `Nothing`, allowing you to differentiate between an explicit `None` value and the absence of a value.

### Result

The `Result` container encapsulates the outcome of operations that can either succeed (`Success`) or fail (`Failure`).

#### Creation

```python
from returns.result import Result, Success, Failure

def find_user(user_id: int) -> Result['User', str]:
    user = User.objects.filter(id=user_id)
    if user.exists():
        return Success(user[0])
    return Failure('User was not found')

user_search_result = find_user(1)  # <Success: User{id: 1, ...}>
user_search_result = find_user(0)  # <Failure: User was not found>
```

#### Composition Example

```python
from returns.result import Result, Success, Failure, safe

@safe
def divide(first_number: int, second_number: int) -> int:
    return first_number // second_number

result = divide(1, 0)

match result:
    case Success(10):
        print('Result is "10"')
    case Success(value):
        print(f'Result is "{value}"')
    case Failure(ZeroDivisionError()):
        print('"ZeroDivisionError" was raised')
    case Failure(_):
        print('The division was a failure')
```

#### Aliases

- **`ResultE`**: An alias for `Result[..., Exception]`, useful when working with exceptions as error types.

### IO

The `IO` container marks impure operations, allowing you to handle side effects explicitly.

#### Creation

```python
from returns.io import IO

def get_random_number() -> IO[int]:
    import random
    return IO(random.randint(1, 10))

random_io = get_random_number()
print(random_io)  # IO(5)
```

#### Composing with `map`

```python
io = get_random_number().map(lambda number: number / number)
print(io)  # IO(1.0)
```

#### Handling IO with Dependencies

```python
from returns.io import IOResult, IOSuccess
from returns.pointfree import map_

def process_booking_result(is_successful: bool) -> 'ProcessID':
    # Process the result
    ...

def can_book_seats(number_of_seats: int, place_id: int) -> IOResult[bool, str]:
    # Perform booking logic
    ...

message_id: IOResult['ProcessID', str] = can_book_seats(2, 10).map(process_booking_result)
```

#### Unsafe Operations

```python
from returns.unsafe import unsafe_perform_io
from returns.io import IO

def index_view(request, user_id):
    user: IO['User'] = get_user(user_id)
    return render('index.html', {'user': unsafe_perform_io(user)})
```

**Warning:** Use `unsafe_perform_io` sparingly as it breaks the purity guarantees provided by Returns.

### Future

The `Future` container facilitates asynchronous programming without explicit `await` statements, integrating seamlessly with event loops like `asyncio`, `trio`, and `curio`.

#### Creation and Composition

```python
from returns.future import Future

async def first() -> int:
    return 1

async def second(arg: int) -> int:
    return arg + 1

def main() -> Future[int]:
    return Future(first()).bind_awaitable(second)

import anyio
result = anyio.run(main().awaitable)
print(result)  # IO(2)
```

#### FutureResult

Combines `Future` with `Result` to handle asynchronous operations that can fail.

```python
from returns.future import FutureResult, future_safe
from returns.io import IOSuccess, IOFailure
from returns.iterables import Fold

@future_safe
async def fetch_post(post_id: int) -> dict:
    import httpx
    response = await httpx.get(f'https://jsonplaceholder.typicode.com/posts/{post_id}')
    response.raise_for_status()
    return response.json()

def show_titles(number_of_posts: int) -> list[FutureResult[str, Exception]]:
    return [fetch_post(post_id).map(lambda post: post['title']) for post_id in range(1, number_of_posts + 1)]

async def main() -> IOResultE[list[str]]:
    import asyncio
    futures = await asyncio.gather(*show_titles(3))
    return Fold.collect(futures, IOSuccess(()))

print(anyio.run(main()))  # <IOResult: <Success: [...]>>
```

#### Decorators

- **`@future`**: Transforms an `async def` function into a `Future` container.
  
    ```python
    from returns.future import future, Future
    import anyio

    @future
    async def test(arg: int) -> float:
        return arg / 2

    future_instance = test(1)
    print(isinstance(future_instance, Future))  # True
    print(anyio.run(future_instance.awaitable))  # IO(0.5)
    ```

- **`@future_safe`**: Converts an `async def` function into a `FutureResult`, handling exceptions gracefully.
  
    ```python
    from returns.future import future_safe, FutureResult
    import anyio

    @future_safe
    async def test(arg: int) -> float:
        return 1 / arg

    future_instance = test(2)
    print(anyio.run(future_instance.awaitable))  # <IOResult: <Success: 0.5>>

    print(anyio.run(test(0).awaitable))  # <IOResult: <Failure: division by zero>>
    ```

- **`asyncify`**: Transforms a synchronous function into an asynchronous one.
  
    ```python
    from returns.future import asyncify
    import anyio

    @asyncify
    def your_function(x: int) -> int:
        return x + 1

    print(anyio.run(your_function, 1))  # 2
    ```

**Note:** Decorating a function with `@asyncify` doesn't make it non-blocking. Avoid using it with blocking operations like `requests.get`.

---

## Helpers and Utilities

### Converters

Returns provides converters to switch between different container types, enabling flexibility in how you handle values and errors.

### `unsafe_perform_io`

Use `unsafe_perform_io` to extract the raw value from an `IO` container when necessary. This is primarily for compatibility with imperative codebases.

```python
from returns.unsafe import unsafe_perform_io
from returns.io import IO

user_io = IO('John Doe')
user = unsafe_perform_io(user_io)
print(user)  # John Doe
```

**Caution:** Using `unsafe_perform_io` bypasses the safety guarantees of Returns. Use it sparingly and prefer maintaining functional purity.

---

## FAQs

### How Can I Turn Maybe into Optional Again?

You can extract an `Optional` value from a `Maybe` container using the `.value_or()` method:

```python
from returns.maybe import Maybe

some_optional = Maybe.from_optional(1).value_or(None)
print(some_optional)  # 1

none_optional = Maybe.from_optional(None).value_or(None)
print(none_optional)  # None
```

### How to Model Absence of Value vs. Presence of None Value?

Use `Some(None)` to represent the presence of a `None` value and `Nothing` to represent the absence of a value.

```python
from returns.maybe import Maybe, Some, Nothing

values = {'a': 1, 'b': None}

print(Maybe.from_value(values).map(lambda d: d.get('a')))  # <Some: 1>
print(Maybe.from_value(values).map(lambda d: d.get('b')))  # <Some: None>
print(Maybe.from_value(values).map(lambda d: d.get('c')))  # <Nothing>
```

### Why There’s No IOMaybe?

Combining `IO` with `Maybe` (`IOMaybe`) is not provided because `IO` already handles side effects, and `Maybe`'s purpose is limited to `None` handling, which isn't as useful in the context of IO operations. Instead, use `Result` with `IO` for error handling in IO contexts.

### Why Maybe Does Not Have `alt` Method?

`Maybe` only has a single failed state (`Nothing`), which cannot be altered, making the `alt` method unnecessary. Instead, use `or_else_call` to handle failed states:

```python
from returns.maybe import Some, Nothing

print(Some(1).or_else_call(lambda: 2))  # 1
print(Nothing.or_else_call(lambda: 2))  # 2
```

### How to Create Unit Objects for Containers?

- **Result:**

    ```python
    from returns.result import Result, Success, Failure

    success = Success(1)
    failure = Failure("Error")
    ```

- **IOResult:**

    ```python
    from returns.io import IOResult, IOSuccess, IOFailure

    success_io = IOSuccess(1)
    failure_io = IOFailure("IO Error")
    ```

### How to Compose Error Types?

Use `unify` from `returns.pointfree` to compose different error types, allowing the error type to be a union of multiple types.

```python
from returns.result import Result, Success, Failure
from returns.pointfree import unify

def div(number: int) -> Result[float, ZeroDivisionError]:
    if number:
        return Success(1 / number)
    return Failure(ZeroDivisionError('division by zero'))

container: Result[int, ValueError] = Success(1)
result = unify(div)(container)
print(result)  # <Success: 1.0>
```

**Revealed Type:** `Result[float, Union[ValueError, ZeroDivisionError]]`

### Map vs. Bind

- **`map`**: Use with pure functions that do not produce side effects.
- **`bind`**: Use with functions that return a `Result` container, handling potential side effects.

```python
from returns.result import Failure, Result, Success, safe

@safe
def parse_json(arg: str) -> dict:
    import json
    return json.loads(arg)

success = Success('{"key": "value"}').bind(parse_json)
print(success)  # <Success: {'key': 'value'}>

failure = Success('').bind(parse_json)
print(failure)  # <Failure: Expecting value: line 1 column 1 (char 0)>
```

### How to Check if Your Result is a Success or Failure?

Use the `is_successful` function from `returns.pipeline`:

```python
from returns.result import Success, Failure
from returns.pipeline import is_successful

print(is_successful(Success(1)))       # True
print(is_successful(Failure('error'))) # False
```

