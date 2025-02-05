"""Modifies the formatting of API documentation."""

import functools
import re
from typing import (
    List,
    TYPE_CHECKING,
    cast,
    Optional,
    Dict,
    Tuple,
    NamedTuple,
    Any,
    Pattern,
    Union,
)

import docutils.nodes
import pydantic
import sphinx.addnodes
import sphinx.application
import sphinx.directives
import sphinx.environment
import sphinx.locale
import sphinx.util.logging
import sphinx.writers.html5
from typing_extensions import Literal

_ = sphinx.locale._

logger = sphinx.util.logging.getLogger(__name__)

ObjectDescriptionOptions = Dict[str, Any]


if TYPE_CHECKING:
    HTMLTranslatorMixinBase = sphinx.writers.html5.HTML5Translator
else:
    HTMLTranslatorMixinBase = object


class HTMLTranslatorMixin(HTMLTranslatorMixinBase):  # pylint: disable=abstract-method
    """Mixin for HTMLTranslator that adds additional CSS classes."""

    def visit_desc(
        self, node: Union[sphinx.addnodes.desc, docutils.nodes.Element]
    ) -> None:
        # Object description node

        # These are converted to `<dl>` elements with the domain and objtype
        # as classes.

        # Augment the list of classes with `objdesc` to make it easier to
        # style these without resorting to hacks.
        node["classes"].append("objdesc")
        super().visit_desc(node)

    def visit_desc_type(
        self, node: Union[sphinx.addnodes.desc_type, docutils.nodes.Element]
    ) -> None:
        self.body.append(
            self.starttag(node, tagname="span", suffix="", CLASS="desctype")
        )

    def depart_desc_type(
        self, node: Union[sphinx.addnodes.desc_type, docutils.nodes.Element]
    ) -> None:
        self.body.append("</span>")

    def visit_desc_parameterlist(
        self, node: Union[sphinx.addnodes.desc_parameterlist, docutils.nodes.Element]
    ) -> None:
        super().visit_desc_parameterlist(node)
        open_paren, _ = node.get("parens", ("(", ")"))
        self.body[-1] = self.body[-1].replace("(", open_paren)

    def depart_desc_parameterlist(
        self, node: Union[sphinx.addnodes.desc_parameterlist, docutils.nodes.Element]
    ) -> None:
        super().depart_desc_parameterlist(node)
        _, close_paren = node.get("parens", ("(", ")"))
        self.body[-1] = self.body[-1].replace(")", close_paren)

    def visit_desc_parameter(
        self, node: Union[sphinx.addnodes.desc_parameter, docutils.nodes.Element]
    ) -> None:
        self.body.append('<span class="sig-param-decl">')
        super().visit_desc_parameter(node)

    def depart_desc_parameter(
        self, node: Union[sphinx.addnodes.desc_parameter, docutils.nodes.Element]
    ) -> None:
        super().depart_desc_parameter(node)
        self.body.append("</span>")

    def depart_field_name(self, node: docutils.nodes.Element) -> None:
        self.add_permalink_ref(node, _("Permalink to this headline"))
        super().depart_field_name(node)

    def depart_term(self, node: docutils.nodes.Element) -> None:
        if "ids" in node.attributes:
            self.add_permalink_ref(node, _("Permalink to this definition"))
        super().depart_term(node)

    def visit_caption(self, node: docutils.nodes.Element) -> None:
        attributes = {"class": "caption-text"}
        if isinstance(node.parent, docutils.nodes.container) and node.parent.get(
            "literal_block"
        ):
            # add highlight class to caption's div container.
            # This is needed to trigger mkdocs-material CSS rule `.highlight .filename`
            self.body.append('<div class="code-block-caption highlight">')
            # append a CSS class to trigger mkdocs-material theme's caption CSS style
            attributes["class"] += " filename"
        else:
            super().visit_caption(node)
        self.add_fignumber(node.parent)
        self.body.append(self.starttag(node, "span", **attributes))

    def depart_caption(self, node: docutils.nodes.Element) -> None:
        if not isinstance(
            node.parent, docutils.nodes.container
        ) and not node.parent.get("literal_block"):
            # only append ending tag if parent is not a literal-block.
            # Because all elements in the caption should be within a span element
            self.body.append("</span>")

        # append permalink if available
        if isinstance(node.parent, docutils.nodes.container) and node.parent.get(
            "literal_block"
        ):
            self.add_permalink_ref(node.parent, _("Permalink to this code"))
            self.body.append("</span>")  # done; add closing tag
        elif isinstance(node.parent, docutils.nodes.figure):
            self.add_permalink_ref(node.parent, _("Permalink to this image"))
        elif node.parent.get("toctree"):
            self.add_permalink_ref(node.parent.parent, _("Permalink to this toctree"))

        if isinstance(node.parent, docutils.nodes.container) and node.parent.get(
            "literal_block"
        ):
            self.body.append("</div>\n")
        else:
            super().depart_caption(node)

    # `desc_inline` nodes are generated by the `cpp:expr` role.
    #
    # Wrap it in a `<code>` element with the "highlight" class to ensure it
    # displays properly as an inline code literal.
    def visit_desc_inline(
        self, node: Union[sphinx.addnodes.desc_inline, docutils.nodes.Element]
    ) -> None:
        self.body.append(
            self.starttag(node, tagname="code", suffix="", CLASS="highlight")
        )

    def depart_desc_inline(
        self, node: Union[sphinx.addnodes.desc_inline, docutils.nodes.Element]
    ) -> None:
        self.body.append("</code>")


def _wrap_signature(node: sphinx.addnodes.desc_signature, limit: int):
    """Wraps long function signatures.

    Adds the `sig-wrap` class which causes each parameter to be displayed on a
    separate line.
    """
    node_text = node.astext()
    if len(node_text) > limit:
        node["classes"].append("sig-wrap")


def _wrap_signatures(
    app: sphinx.application.Sphinx,
    domain: str,
    objtype: str,
    content: docutils.nodes.Element,
) -> None:
    env = app.env
    assert env is not None
    options = get_object_description_options(env, domain, objtype)
    if (
        not options["wrap_signatures_with_css"]
        or options.get("clang_format_style") is not None
    ):
        return
    signatures = content.parent[:-1]
    for signature in signatures:
        assert isinstance(signature, sphinx.addnodes.desc_signature)
        _wrap_signature(signature, options["wrap_signatures_column_limit"])


def _monkey_patch_object_description_to_include_fields_in_toc():
    orig_run = sphinx.directives.ObjectDescription.run

    def run(self: sphinx.directives.ObjectDescription) -> List[docutils.nodes.Node]:
        nodes = orig_run(self)

        options = get_object_description_options(self.env, self.domain, self.objtype)
        if not options["include_fields_in_toc"]:
            return nodes

        obj_desc = nodes[-1]

        obj_id = None
        for sig in obj_desc[:-1]:
            ids = sig["ids"]
            if ids and ids[0]:
                obj_id = ids[0]
                break

        obj_content = obj_desc[-1]
        for child in obj_content:
            if not isinstance(child, docutils.nodes.field_list):
                continue
            for field in child:
                assert isinstance(field, docutils.nodes.field)
                field_name = cast(docutils.nodes.field_name, field[0])
                if field_name["ids"]:
                    continue
                field_id = docutils.nodes.make_id(field_name.astext())
                if obj_id:
                    field_id = f"{obj_id}-{field_id}"
                field_name["ids"].append(field_id)

        return nodes

    sphinx.directives.ObjectDescription.run = run


def format_object_description_tooltip(
    env: sphinx.environment.BuildEnvironment,
    options: ObjectDescriptionOptions,
    base_title: str,
    synopsis: Optional[str],
) -> str:
    title = base_title

    domain = env.get_domain(options["domain"])

    if options["include_object_type_in_xref_tooltip"]:
        object_type = options["object_type"]
        title += f" ({domain.get_type_name(domain.object_types[object_type])})"

    if synopsis:
        title += f" — {synopsis}"

    return title


DEFAULT_OBJECT_DESCRIPTION_OPTIONS: List[Tuple[str, dict]] = [
    ("std:envvar", {"toc_icon_class": "alias", "toc_icon_text": "$"}),
    ("js:module", {"toc_icon_class": "data", "toc_icon_text": "r"}),
    ("js:function", {"toc_icon_class": "procedure", "toc_icon_text": "M"}),
    ("js:method", {"toc_icon_class": "procedure", "toc_icon_text": "M"}),
    ("js:class", {"toc_icon_class": "data", "toc_icon_text": "C"}),
    ("js:data", {"toc_icon_class": "alias", "toc_icon_text": "V"}),
    ("js:attribute", {"toc_icon_class": "alias", "toc_icon_text": "V"}),
    ("json:schema", {"toc_icon_class": "data", "toc_icon_text": "J"}),
    ("json:subschema", {"toc_icon_class": "sub-data", "toc_icon_text": "j"}),
    ("py:class", {"toc_icon_class": "data", "toc_icon_text": "C"}),
    ("py:function", {"toc_icon_class": "procedure", "toc_icon_text": "F"}),
    ("py:method", {"toc_icon_class": "procedure", "toc_icon_text": "M"}),
    ("py:classmethod", {"toc_icon_class": "procedure", "toc_icon_text": "M"}),
    ("py:staticmethod", {"toc_icon_class": "procedure", "toc_icon_text": "M"}),
    ("py:property", {"toc_icon_class": "alias", "toc_icon_text": "P"}),
    ("py:attribute", {"toc_icon_class": "alias", "toc_icon_text": "A"}),
    ("py:data", {"toc_icon_class": "alias", "toc_icon_text": "V"}),
    ("py:parameter", {"toc_icon_class": "sub-data", "toc_icon_text": "p"}),
    ("c:member", {"toc_icon_class": "alias", "toc_icon_text": "V"}),
    ("c:var", {"toc_icon_class": "alias", "toc_icon_text": "V"}),
    ("c:function", {"toc_icon_class": "procedure", "toc_icon_text": "F"}),
    ("c:macro", {"toc_icon_class": "alias", "toc_icon_text": "D"}),
    ("c:union", {"toc_icon_class": "data", "toc_icon_text": "U"}),
    ("c:struct", {"toc_icon_class": "data", "toc_icon_text": "S"}),
    ("c:enum", {"toc_icon_class": "data", "toc_icon_text": "E"}),
    ("c:enumerator", {"toc_icon_class": "data", "toc_icon_text": "e"}),
    ("c:type", {"toc_icon_class": "alias", "toc_icon_text": "T"}),
    (
        "c:macroParam",
        {
            "toc_icon_class": "sub-data",
            "toc_icon_text": "p",
            "generate_synopses": "first_sentence",
        },
    ),
    ("cpp:class", {"toc_icon_class": "data", "toc_icon_text": "C"}),
    ("cpp:struct", {"toc_icon_class": "data", "toc_icon_text": "S"}),
    ("cpp:enum", {"toc_icon_class": "data", "toc_icon_text": "E"}),
    ("cpp:enum-class", {"toc_icon_class": "data", "toc_icon_text": "E"}),
    ("cpp:enum-struct", {"toc_icon_class": "data", "toc_icon_text": "E"}),
    ("cpp:enumerator", {"toc_icon_class": "data", "toc_icon_text": "e"}),
    ("cpp:union", {"toc_icon_class": "data", "toc_icon_text": "U"}),
    ("cpp:concept", {"toc_icon_class": "data", "toc_icon_text": "t"}),
    ("cpp:function", {"toc_icon_class": "procedure", "toc_icon_text": "F"}),
    ("cpp:alias", {"toc_icon_class": "procedure", "toc_icon_text": "F"}),
    ("cpp:member", {"toc_icon_class": "alias", "toc_icon_text": "V"}),
    ("cpp:var", {"toc_icon_class": "alias", "toc_icon_text": "V"}),
    ("cpp:type", {"toc_icon_class": "alias", "toc_icon_text": "T"}),
    ("cpp:namespace", {"toc_icon_class": "alias", "toc_icon_text": "N"}),
    (
        "cpp:functionParam",
        {
            "toc_icon_class": "sub-data",
            "toc_icon_text": "p",
            "generate_synopses": "first_sentence",
        },
    ),
    (
        "cpp:templateTypeParam",
        {
            "toc_icon_class": "alias",
            "toc_icon_text": "T",
            "generate_synopses": "first_sentence",
        },
    ),
    (
        "cpp:templateNonTypeParam",
        {
            "toc_icon_class": "data",
            "toc_icon_text": "N",
            "generate_synopses": "first_sentence",
        },
    ),
    (
        "cpp:templateTemplateParam",
        {
            "toc_icon_class": "alias",
            "toc_icon_text": "T",
            "generate_synopses": "first_sentence",
        },
    ),
    ("rst:directive", {"toc_icon_class": "data", "toc_icon_text": "D"}),
    ("rst:directive:option", {"toc_icon_class": "sub-data", "toc_icon_text": "o"}),
    ("rst:role", {"toc_icon_class": "procedure", "toc_icon_text": "R"}),
]


def get_object_description_option_registry(app: sphinx.application.Sphinx):
    key = "sphinx_immaterial_object_description_option_registry"
    registry = getattr(app, key, None)
    if registry is None:
        registry = {}
        setattr(app, key, registry)
    return registry


class RegisteredObjectDescriptionOption(NamedTuple):
    type_constraint: Any
    default: Any


def add_object_description_option(
    app: sphinx.application.Sphinx, name: str, default: Any, type_constraint: Any = Any
) -> None:
    registry = get_object_description_option_registry(app)
    if name in registry:
        logger.error(f"Object description option {name!r} already registered")
    default = pydantic.parse_obj_as(type_constraint, default)
    registry[name] = RegisteredObjectDescriptionOption(
        default=default, type_constraint=type_constraint
    )


def get_object_description_options(
    env: sphinx.environment.BuildEnvironment, domain: str, object_type: str
) -> ObjectDescriptionOptions:

    return env.app._sphinx_immaterial_get_object_description_options(  # type: ignore
        domain, object_type
    )


def _builder_inited(app: sphinx.application.Sphinx) -> None:

    registry = get_object_description_option_registry(app)
    options_map: Dict[str, List[Tuple[int, Dict[str, Any]]]] = {}
    options_patterns: List[Tuple[Pattern, int, Dict[str, Any]]] = []

    default_options = {}
    for name, registered_option in registry.items():
        default_options[name] = registered_option.default

    # Validate options
    for i, (pattern, options) in enumerate(
        pydantic.parse_obj_as(
            List[Tuple[Pattern, Dict[str, Any]]],
            DEFAULT_OBJECT_DESCRIPTION_OPTIONS + app.config.object_description_options,
        )
    ):
        for name, value in options.items():
            registered_option = registry.get(name)
            if registered_option is None:
                logger.error(
                    "Undefined object description option %r specified for pattern %r",
                    name,
                    pattern.pattern,
                )
                continue
            try:
                options[name] = pydantic.parse_obj_as(
                    registered_option.type_constraint, value
                )
            except Exception as e:  # pylint: disable=broad-except
                logger.error(
                    "Invalid value %r for object description option"
                    " %r specified for pattern %r: %s",
                    value,
                    name,
                    pattern.pattern,
                    e,
                )
        if pattern.pattern == re.escape(pattern.pattern):
            # Pattern just matches a single string.
            options_map.setdefault(pattern.pattern, []).append((i, options))
        else:
            options_patterns.append((pattern, i, options))

    @functools.lru_cache(maxsize=None)
    def get_options(domain: str, object_type: str) -> Dict[str, Any]:
        key = f"{domain}:{object_type}"
        matches = options_map.get(key)
        if matches is None:
            matches = []
        else:
            matches = list(matches)
        for pattern, i, options in options_patterns:
            if pattern.fullmatch(key):
                matches.append((i, options))
        matches.sort(key=lambda x: x[0])
        full_options = default_options.copy()
        for _, m in matches:
            full_options.update(m)
        full_options.update(domain=domain, object_type=object_type)
        return full_options

    app._sphinx_immaterial_get_object_description_options = get_options  # type: ignore


def setup(app: sphinx.application.Sphinx):
    """Registers the monkey patches.

    Does not register HTMLTranslatorMixin, the caller must do that.
    """
    # Add "highlight" class in order for pygments syntax highlighting CSS rules
    # to apply.
    sphinx.addnodes.desc_signature.classes.append("highlight")

    app.connect("object-description-transform", _wrap_signatures)
    _monkey_patch_object_description_to_include_fields_in_toc()

    add_object_description_option(
        app, "wrap_signatures_with_css", type_constraint=bool, default=True
    )
    add_object_description_option(
        app, "wrap_signatures_column_limit", type_constraint=int, default=68
    )
    add_object_description_option(
        app, "include_in_toc", type_constraint=bool, default=True
    )
    add_object_description_option(
        app, "include_fields_in_toc", type_constraint=bool, default=True
    )
    add_object_description_option(
        app,
        "generate_synopses",
        type_constraint=Optional[Literal["first_paragraph", "first_sentence"]],
        default="first_paragraph",
    )
    add_object_description_option(
        app, "include_object_type_in_xref_tooltip", type_constraint=bool, default=True
    )
    add_object_description_option(
        app, "toc_icon_text", type_constraint=Optional[str], default=None
    )
    add_object_description_option(
        app, "toc_icon_class", type_constraint=Optional[str], default=None
    )

    app.add_config_value(
        "object_description_options",
        default=[],
        rebuild="env",
        types=(List[Tuple[Pattern, Dict[str, Any]]],),
    )
    app.connect("builder-inited", _builder_inited)

    return {
        "parallel_read_safe": True,
        "parallel_write_safe": True,
    }
