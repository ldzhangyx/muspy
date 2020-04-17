"""
Music object
============

This is the core class of MusPy.

"""
from bisect import bisect_left
from collections import OrderedDict
from pathlib import Path
from typing import List, Optional, Union

from pretty_midi import PrettyMIDI
from pypianoroll import Multitrack

from .base import ComplexBase
from .classes import (
    Annotation,
    KeySignature,
    Lyric,
    MetaData,
    Tempo,
    TimeSignature,
    Timing,
    Track,
)
from .outputs import (
    save,
    save_json,
    save_yaml,
    to_object,
    to_pretty_midi,
    to_pypianoroll,
    write,
    write_midi,
    write_musicxml,
)
from .representations import to_representation

__all__ = ["Music"]

# pylint: disable=super-init-not-called


class Music(ComplexBase):
    """A simple yet universal container for symbolic music.

    This is the core class of MusPy, which provides I/O interfaces for common
    formats. A Music object can be constructed in the following ways.

    - :meth:`muspy.Music`: Construct by setting values for attributes.
    - :meth:`muspy.Music.from_dict`: Construct from a dictionary that stores
      the attributes and their values as key-value pairs.
    - :func:`muspy.read`: Read from a MIDI or a MusicXML file.
    - :func:`muspy.load`: Load from a JSON or a YAML file saved by
      :func:`muspy.save` or :class:`muspy.Music.save`.
    - :func:`muspy.from_object`: Convert from a :class:`pretty_midi.PrettyMIDI`
      or :class:`pypianoroll.Multitrack` object.

    Attributes
    ----------
    meta : :class:`muspy.MetaData` object
        Meta data. See :class:`muspy.MetaData` for details.
    timing : :class:`muspy.Timing` object
        A timing info object. See :class:`muspy.Timing` for details.
    key_signatures : list of :class:`muspy.KeySignature` object
        Time signatures. See :class:`muspy.KeySignature` for details.
    time_signatures : list of :class:`muspy.TimeSignature` object
        Time signatures. See :class:`muspy.TimeSignature` for details.
    downbeats : list of int or float
        Downbeat positions.
    lyrics : list of :class:`muspy.Lyric`
        Lyrics. See :class:`muspy.Lyric` for details.
    annotations : list of :class:`muspy.Annotation`
        Annotations. See :class:`muspy.Annotation` for details.
    tracks : list of :class:`muspy.Track`
        Music tracks. See :class:`muspy.Track` for details.

    """

    _attributes = OrderedDict(
        [
            ("meta", MetaData),
            ("timing", Timing),
            ("key_signatures", KeySignature),
            ("time_signatures", TimeSignature),
            ("downbeats", float),
            ("lyrics", Lyric),
            ("annotations", Annotation),
            ("tracks", Track),
        ]
    )
    _optional_attributes = ["meta"]
    _temporal_attributes = ["downbeats"]
    _list_attributes = [
        "key_signatures",
        "time_signatures",
        "downbeats",
        "lyrics",
        "annotations",
        "tracks",
    ]

    def __init__(
        self,
        meta: Optional[MetaData] = None,
        timing: Optional[Timing] = None,
        key_signatures: Optional[List[KeySignature]] = None,
        time_signatures: Optional[List[TimeSignature]] = None,
        downbeats: Optional[List[float]] = None,
        lyrics: Optional[List[Lyric]] = None,
        annotations: Optional[List[Annotation]] = None,
        tracks: Optional[List[Track]] = None,
    ):
        self.meta = meta
        self.timing = timing if timing is not None else Timing()
        self.key_signatures = (
            key_signatures if key_signatures is not None else []
        )
        self.time_signatures = (
            time_signatures if time_signatures is not None else []
        )
        self.downbeats = downbeats if downbeats is not None else []
        self.lyrics = lyrics if lyrics is not None else []
        self.annotations = annotations if annotations is not None else []
        self.tracks = tracks if tracks is not None else []

    def remove_duplicate_changes(self):
        """Remove duplicate key signature, time signature and tempo changes."""
        self.timing.remove_duplicate_changes()

        key_signs = self.key_signatures
        self.key_signatures = [
            next_key_sign
            for key_sign, next_key_sign in zip(key_signs[:-1], key_signs[1:])
            if key_sign.numerator != next_key_sign.numerator
            or key_sign.denominator != next_key_sign.denominator
        ]
        self.key_signatures.insert(0, key_signs[0])

        time_signs = self.time_signatures
        self.time_signatures = [
            next_time_sign
            for time_sign, next_time_sign in zip(
                time_signs[:-1], time_signs[1:]
            )
            if time_sign.numerator != next_time_sign.numerator
            or time_sign.denominator != next_time_sign.denominator
        ]
        self.time_signatures.insert(0, time_signs[0])

    def get_end_time(self, is_sorted: bool = False) -> float:
        """Return the time of the last event in all tracks.

        This includes tempos, key signatures, time signatures, notes offsets,
        lyrics and annotations.

        Parameters
        ----------
        is_sorted : bool
            Whether all the list attributes are sorted. Defaults to False.

        """

        def _get_end_time(list_):
            if not list_:
                return 0
            if is_sorted:
                return list_[-1].time
            return max(item.time for item in list_)

        if self.tracks:
            track_end_time = max(
                track.get_end_time(is_sorted) for track in self.tracks
            )
        else:
            track_end_time = 0
        return max(
            self.timing.get_end_time(is_sorted),
            _get_end_time(self.key_signatures),
            _get_end_time(self.time_signatures),
            _get_end_time(self.lyrics),
            _get_end_time(self.annotations),
            track_end_time,
        )

    def adjust_resolution(
        self, target: Optional[int] = None, factor: Optional[float] = None
    ):
        """Adjust resolution and update the timing of time-stamped objects.

        Parameters
        ----------
        target : int, optional
            Target resolution.
        factor : int or float, optional
            Factor used to adjust the resolution based on the formula:
            `new_resolution = old_resolution * factor`. For example, a factor of
            2 double the resolution, and a factor of 0.5 halve the resolution.

        """
        if not self.timing.is_symbolic:
            raise ValueError("Only works for music object in symbolic timing.")
        if self.timing.resolution is None:
            raise TypeError("`resolution` must not be None.")
        if self.timing.resolution < 0:
            raise ValueError("`resolution` must be positive.")

        if target is None and factor is None:
            raise ValueError("`target` and `factor` must not be both None.")
        if target is not None and factor is not None:
            raise ValueError("Either `target` or `factor` must be given.")

        if target is not None:
            if not isinstance(target, int):
                raise TypeError("`target` must be an integer.")
            target_ = int(target)
            factor_ = target / self.timing.resolution

        if factor is not None:
            new_resolution = self.timing.resolution * factor
            if not new_resolution.is_integer():
                raise ValueError(
                    "`factor` must be a factor of the resolution."
                )
            factor_ = float(factor)
            target_ = int(new_resolution)

        self.timing.resolution = int(target_)
        self.adjust_time(lambda time: round(time / factor_))

    def append(self, obj):
        """Append an object to the correseponding list.

        Parameters
        ----------
        obj : Muspy objects (see below)
            Object to be appended. Supported object types are
            :class:`muspy.KeySignature`, :class:`muspy.TimeSignature`,
            :class:`muspy.Tempo`, :class:`muspy.Lyric`,
            :class:`muspy.Annotation` and :class:`muspy.Track` objects.

        """
        if isinstance(obj, Tempo):
            self.timing.tempos.append(obj)
        self._append(obj)

    def clip(self, lower: float = 0, upper: float = 127):
        """Clip the velocity of each note for each track.

        Parameters
        ----------
        lower : int or float, optional
            Lower bound. Defaults to 0.
        upper : int or float, optional
            Upper bound. Defaults to 127.

        """
        for track in self.tracks:
            track.clip(lower, upper)

    def quantize(
        self,
        resolution: int,
        beats: Optional[List[float]] = None,
        bpm: Optional[float] = None,
        offset: float = 0,
        update_tempos: bool = True,
    ):
        """Quantize the timing of time-stamped objects.

        If `beats` is given, use it as the beat locations and quantize the
        timing accordingly.

        Parameters
        ----------
        resolution : int
            Time steps per beat.
        beats : list of float, optional
            Sorted list of beat positions in ascending order, assuming no
            duplicate values.
        bpm : int or float, optional
            Length of quantization step, in seconds.
        offset : float, optional
            Offset of the beat pulse train. This can be useful to set the start
            time of the first beat. Defaults to 0.
        update_tempos : bool, optional
            Whether to update the tempos. Defaults to True.

        """
        if resolution is None:
            raise TypeError("`resolution` must not be None.")

        # Validate the timing
        self.timing.validate()
        if self.timing.is_symbolic:
            raise ValueError("Only works for music object in absolute timing.")

        if beats is None:
            if bpm is None:
                raise TypeError("`bpm` must not be None when `beats` is None.")
            factor = 60 * resolution / bpm
            self.adjust_time(lambda time: round((time - offset) * factor))
            self.timing.is_symbolic = True
            self.timing.resolution = resolution
            if update_tempos:
                self.timing.tempos = [Tempo(0.0, bpm)]

        else:
            # Get the anchor points (midpoints of adjacent beat locations)
            anchors = [
                (beat + next_beat) / 2
                for beat, next_beat in zip(beats[:-1], beats[1:])
            ]
            # The first anchor points is at the first beat
            anchors.insert(0, beats[0])

            self.adjust_time(lambda time: bisect_left(anchors, time))
            self.timing.is_symbolic = True
            self.timing.resolution = resolution
            if update_tempos:
                raise NotImplementedError
                # self.timing.tempos = ...

    def sort(self):
        """Sort the time-stamped objects with respect to event time.

        This will sort tempos, key signatures, time signatures, lyrics and
        annotations, along with notes, lyrics and annotations for each track.

        """
        self.timing.sort(key=lambda x: x.time)
        self.key_signatures.sort(key=lambda x: x.time)
        self.time_signatures.sort(key=lambda x: x.time)
        self.lyrics.sort(key=lambda x: x.time)
        self.annotations.sort(key=lambda x: x.time)
        for track in self.tracks:
            track.sort()

    def transpose(self, semitone: int):
        """Transpose all the notes for all tracks by a number of semitones.

        Parameters
        ----------
        semitone : int
            Number of semitones to transpose the notes. A positive value raises
            the pitches, while a negative value lowers the pitches.

        """
        for track in self.tracks:
            track.transpose(semitone)

    def save(self, path: Union[str, Path]):
        """Save loselessly to a JSON or a YAML file.

        Refer to :func:`muspy.save`: for full documentation.

        Parameters
        ----------
        path : str or Path
            Path to save the file. The file format is inferred from the
            extension.

        See Also
        --------
        :func:`muspy.write`: Write to other formats such as MIDI and MusicXML.

        """
        save(self, path)

    def save_json(self, path: Union[str, Path]):
        """Save loselessly to a JSON file.

        Refer to :func:`muspy.save_json`: for full documentation.

        Parameters
        ----------
        path : str or Path
            Path to save the JSON file.

        """
        save_json(self, path)

    def save_yaml(self, path: Union[str, Path]):
        """Save loselessly to a YAML file.

        Refer to :func:`muspy.save_yaml`: for full documentation.

        Parameters
        ----------
        path : str or Path
            Path to save the YAML file.

        """
        save_yaml(self, path)

    def write(self, path: Union[str, Path]):
        """Write to a MIDI or a MusicXML file.

        Refer to :func:`muspy.write`: for full documentation.

        Parameters
        ----------
        path : str or Path
            Path to write the file. The file format is inferred from the
            extension.

        See Also
        --------
        :func:`muspy.save`: Losslessly save to a JSON and a YAML file.

        """
        write(self, path)

    def write_midi(self, path: Union[str, Path], backend=None):
        """Write to a MIDI file.

        Refer to :func:`muspy.write_midi`: for full documentation.

        Parameters
        ----------
        path : str or Path
            Path to write the MIDI file.

        """
        write_midi(self, path, backend)

    def write_musicxml(self, path: Union[str, Path]):
        """Write to a MusicXML file.

        Refer to :func:`muspy.write_musicxml`: for full documentation.

        Parameters
        ----------
        path : str or Path
            Path to write the MusicXML file.

        """
        write_musicxml(self, path)

    def to_object(self, target: str):
        """Convert to a target class.

        Parameters
        ----------
        target : str
            Target class. Supported values are 'pretty_midi' and 'pypianoroll'.

        """
        return to_object(self, target)

    def to_pretty_midi(self) -> PrettyMIDI:
        """Return as a PrettyMIDI object."""
        return to_pretty_midi(self)

    def to_pypianoroll(self) -> Multitrack:
        """Return as a Multitrack object."""
        return to_pypianoroll(self)

    def to_representation(self, target: str):
        """Convert to a target class.

        Parameters
        ----------
        target : str
            Target representation. Supported values are 'event', 'note' and
            'pianoroll'.

        """
        return to_representation(self, target)

    def to_event_representation(self):
        """Return the event-based representation."""
        to_representation(self, "event")

    def to_note_representation(self):
        """Return the note-based representation."""
        to_representation(self, "note")

    def to_pianoroll_representation(self):
        """Return the pianoroll representation."""
        to_representation(self, "pianoroll")
