"""Read review history inside a CollectionPort.run callback."""

from anki.collection import Collection


def day_start_ms(col: Collection) -> int:
    """Return the collection's current scheduler day start in milliseconds."""
    return (col.sched.day_cutoff - 86400) * 1000


def studied_by_deck(col: Collection) -> dict[int, int]:
    """Count today's reviews in each card's own deck, without child aggregation."""
    assert col.db is not None
    return dict(
        col.db.all(
            "select c.did, count(*) from revlog r join cards c on c.id=r.cid "
            "where r.id > ? group by c.did",
            day_start_ms(col),
        )
    )


def recent_eases(col: Collection, limit: int) -> list[int]:
    """Return today's latest review ratings, newest first."""
    assert col.db is not None
    return col.db.list(
        "select ease from revlog where id > ? order by id desc limit ?",
        day_start_ms(col),
        limit,
    )
