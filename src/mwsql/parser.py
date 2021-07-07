"""Parser functions used in src/dump.py"""

import csv
import re
import warnings
from typing import Any, Dict, Iterator, List, Optional


def _has_sql_attribute(line: str, attr_type: str) -> bool:
    """Check whether a string contains a specific SQL element
    or statement.

    :param line: A line from a SQL dump file.
    :type line: str
    :param attr_type: Element or statement type, e.g "primary_key"
        for a table's primary key or "insert" for INSERT INTO statements.
    :type attr_type: str
    :return: True or False
    :rtype: bool
    """

    # FYI: no need to update this because I think it's nice and simple but if you were trying to
    # expand it to more use cases and finding the rules to get more complex, you would likely want to consider
    # a regex for each like in get_sql_attribute.
    # e.g., something like (with the caveat that I am not good at regexes): re.match('(^--).*(Database: )', line)
    line_start = {
        "database": "--",
        "insert": "INSERT INTO",
        "create": "CREATE TABLE",
        "primary_key": "PRIMARY KEY",
        "col_name": "`",
    }
    contains_element = line.strip().startswith(line_start[attr_type])

    if attr_type == "database":
        return contains_element and "Database: " in line

    return contains_element


def _get_sql_attribute(line: str, attr_type: str) -> Optional[str]:
    """Extract a SQL attribute from a string that contains it.

    :param line: A line from a SQL dump file.
    :type line: str
    :param attr_type: Element or statement type, e.g "primary_key"
        for a table's primary key or "col_name" for a column (field) name.
    :type attr_type: str
    :return: A SQL attribute such as database(name), table name,
        primary_key, etc.
    :rtype: Optional[str]
    """

    attr_pattern = {
        "table_name": r"`([\S]*)`",
        "col_name": r"`([\S]*)`",
        "dtype": r"` ((.)*),",
        "primary_key": r"`([\S]*)`",
    }

    attr: Optional[str] = None

    try:
        if attr_type == "database":
            attr = line.strip().partition("Database: ")[-1]

        elif attr_type in ("table_name", "col_name", "dtype"):
            attr = re.search(attr_pattern[attr_type], line).group(1)  # type: ignore

        elif attr_type == "primary_key":
            attr = (
                re.search(attr_pattern[attr_type], line)
                .group(1)  # type: ignore
                .replace("`", "")
                .split(",")
            )

    except AttributeError:
        return None

    # probably define attr as None before the try clause. right now if not of the if-else clauses matched, would throw a weird error
    # Done!
    return attr


# I don't know much about the intricacies of types but I like this -- good and simple!
def _map_dtypes(sql_dtypes: Dict[str, str]) -> Dict[str, type]:
    """Create mapping from SQL data types to Python data types.

    :param sql_dtypes: A mapping from the column names in a SQL table
        to their respective SQL data types.
        Example: {"ct_id": int(10) unsigned NOT NULL AUTO_INCREMENT}
    :type sql_dtypes: Dict[str, str]
    :return: A mapping from the column names in a SQL table
        to their respective Python data types. Example: {"ct_id": int}
    :rtype: Dict[str, type]
    """

    types: Dict[str, type] = {}
    for key, val in sql_dtypes.items():
        if "int" in val:
            types[key] = int
        elif any(dtype in val for dtype in ("float", "double", "decimal", "numeric")):
            types[key] = float
        else:
            types[key] = str
    return types


def _convert(values: List[str], dtypes: List[type], strict: bool = False) -> List[Any]:
    """Cast numerical values in a list of strings to float or int
    as specified by the dtypes parameter.

    :param values: A list of strings representing a row in a SQL table
        E.g. ['28207', 'April', '4742783', '0.9793'].
    :type values: List[str]
    :param dtypes: A list of Python data types. E.g. [int, str, int, float]
    :type dtypes: List[type]
    :param strict: When set to False, if any of the items in the list
        cannot be converted, it is returned unchanged, i.e. as a str.
    :type strict: bool, optional
    :raises ValueError: If `values` is not the same length as `dtypes`,
        or if `strict` is set to True and some of the values in the
        list couldn't be converted.
    :return: A list where the numerical values have been cast as int
        or string as defined by `dtypes`. E.g. the example list from
        above is returned as [28207, 'April', 4742783, 0.9793]
    :rtype: List[Any]
    """

    len_values = len(values)
    len_dtypes = len(dtypes)

    warn = False

    if len_values != len_dtypes:
        if not strict:
            return values

        raise ValueError("values and dtypes are not the same length")

    converted = []
    for i in range(len_dtypes):
        dtype = dtypes[i]
        val = values[i]

        try:
            conv = dtype(val)
            converted.append(conv)

        except ValueError as e:
            if values[i] == "":
                # why not convert to None?
                converted.append(val)
            elif not strict:
                warn = True
                converted.append(val)
            else:
                # my PyCharm installation doesn't like this and things it won't work FYI. I haven't tested it though.
                # You're right - I've changed this now.
                print(f"ValueError: {e}")

    if warn:
        # low priority: perhaps include the values too? or problematic value?
        # > I need to think about how to handle this because some files, notably
        # externallinks, have > 10^3 such values
        warnings.warn("some rows could not be converted to Python dtypes")

    return converted


def _split_tuples(line: str) -> List[str]:
    """Split an INSERT INTO statement into a list of strings each
    representing a SQL table row.

    :param line: An INSERT INTO statement, e.g. "INSERT INTO `change_tag_def`
        VALUES (1,'mw-replace',0,10200),(2,'visualeditor',0,305860);"
    :type line: str
    :return: A list with items representing SQL rows,
        e.g. ["1,'mw-replace',0,10200", "2,'visualeditor',0,305860"]
    :rtype: List[str]
    """

    # I think the NULL replacement might need some tweaking. The challenge is two-fold:
    # * making NULL into something that doesn't break the parser -- that's easy, either add quotes like you do or replace with None
    # > I have opted for replacing NULL with the empty string when it's used
    # to denote missing values (i.e. not part of some other string). The reason
    # is that `None` is somewhat specific to pure Python while Pandas, Numpy, R, CSV, and others recognize the empty string as a missing value and sub it with their own null equivalent (NaN, NA, <na>, ...)
    # * not making this replacement when e.g., NULL is just part of a real value like a page title as happens in Commons sometimes
    # For the latter, I think you might need to a regex that only does the replacement when it sees any of the following
    # which in theory should capture all the ways that NULL shows up as a full field value:
    # * ,NULL,
    # * (NULL,
    # * ,NULL)
    # > Good suggestion - I have implemented this regex.
    tuples = line.partition(" VALUES ")[-1].strip()
    # Sub NULL with the empty string
    pattern = r"(?<=[,(])NULL(?=[,)])"
    values = re.sub(pattern, "", tuples)
    # Remove `;` at the end of the last `INSERT INTO` statement
    if values[-1] == ";":
        values = values[:-1]
    records = re.split(r"\),\(", values[1:-1])  # Strip `(` and `)`

    return records


def _parse(
    line: str,
    delimiter: str = ",",
    escape_char: str = "\\",
    quote_char: str = "'",
    doublequote: bool = False,
    strict: bool = True,
) -> Iterator[List[str]]:
    """Parse an INSERT INTO statement and return a generator that yields from a list of CSV-formatted strings, each representing a SQL table row. This
    is essentially a wrapper around a csv.reader object and takes the same
    parameters, except it takes a string as input instead of an iterator-type
    object.

    :param line: An INSERT INTO statement, e.g. "INSERT INTO `change_tag_def`
        VALUES (1,'mw-replace',0,10200),(2,'visualeditor',0,305860);"
    :type line: str
    :param delimiter: A one-character string used to separate fields,
        defaults to ","
    :type delimiter: str, optional
    :param escape_char: A one-character string used by the reader to remove
        any special meaning from the following character, defaults to "\"
    :type escape_char: str, optional
    :param quote_char: A one-character string used to quote fields
        containing special characters, such as the delimiter or quotechar,
        or which contain new-line characters, defaults to "'"
    :type quote_char: str, optional
    :param doublequote: Controls how instances of quotechar appearing inside
        a field should themselves be quoted. When True, the character
        is doubled. When False, the escapechar is used as a prefix
        to the quotechar. Defaults to False.
    :type doublequote: bool, optional
    :param strict: When True, raise exception Error on bad CSV input.
        Defaults to True.
    :type strict: bool, optional
    :return: A generator that yields from a list of CSV-formatted strings.
    :rtype: Iterator[List[str]]
    """

    records = _split_tuples(line)
    reader = csv.reader(
        records,
        delimiter=delimiter,
        escapechar=escape_char,
        quotechar=quote_char,
        doublequote=doublequote,
        strict=strict,
    )
    return reader
