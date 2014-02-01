import sublime, sublime_plugin, os, json, re
ST2 = int(sublime.version()) < 3000

if ST2:
    # ST 2
    import commands
    import cache
else:
    # ST 3
    from . import commands
    from . import cache

symbol_dict = commands.symbol_dict

cssStyleCompletion = None
pseudo_selector_list = []
scratch_view = None
settings = {}


def plugin_loaded():
    global cssStyleCompletion, settings, pseudo_selector_list

    cssStyleCompletion = CssStyleCompletion(cache.get_cache_path())

    settings = sublime.load_settings('css_style_completions.sublime-settings')
    pseudo_selector_list = settings.get("pseudo_selector_list")

    def init_file_loading():
        if not sublime.active_window():
            sublime.set_timeout(lambda: init_file_loading(), 500)
        else:
            load_external_files(get_external_files())

    init_file_loading()


def get_external_files():
    import glob
    global settings

    external_files = []
    for file_path in settings.get('load_external_files', []):
        external_files.extend(glob.glob(file_path))
    return external_files


def load_external_files(file_list, as_scratch=True):
    global scratch_view
    syntax_file = {
        'css': 'Packages/CSS/CSS.tmLanguage',
        'less': 'Packages/LESS/LESS.tmLanguage',
        'scss': 'Packages/SCSS/SCSS.tmLanguage'
    }

    scratch_view = create_output_panel('CSS Extended Completions')
    scratch_view.set_scratch(as_scratch)
    # sort file list by extension to reduce the frequency
    # of syntax file loads
    sorted(file_list, key=lambda x: x.split(".")[-1])
    current_syntax = {
        'isThis': ''
    }
    file_count = len(file_list)

    def parse_file(file_path, indx):
        global scratch_view, cssStyleCompletion, symbol_dict, settings
        print('PARSING FILE', file_path)
        file_extension = os.path.splitext(file_path)[1][1:]
        if not file_extension in syntax_file:
            return
        if not syntax_file[file_extension] == current_syntax['isThis']:
            scratch_view.set_syntax_file(syntax_file[file_extension])
            current_syntax['isThis'] = syntax_file[file_extension]
        sublime.status_message(
            'CSS Extended: parsing file %s of %s' % (indx + 1, file_count)
        )
        try:
            scratch_view.set_name(file_path)
            with open(file_path, 'r') as f:
                sublime.active_window().run_command(
                    'css_extended_completions_file',
                    {"content": f.read()}
                )
                cache.save_cache(scratch_view, cssStyleCompletion)
        except IOError:
            pass

    parse_delay = 0
    for indx, file_path in enumerate(file_list):
        if not os.path.isfile(file_path):
            continue
        sublime.set_timeout(
            lambda file_path=file_path, indx=indx: parse_file(file_path, indx),
            parse_delay
        )
        parse_delay = parse_delay + 250


class CssExtendedCompletionsFileCommand(sublime_plugin.TextCommand):
        global scratch_view

        def run(self, edit, content):
            # add space between any )} chars
            # ST3 throws an error in some LESS files that do this
            content = re.sub(r'\)\}', r') }', content)
            scratch_view.erase(edit, sublime.Region(0, scratch_view.size()))
            scratch_view.insert(edit, 0, content)


def create_output_panel(name):
    '''
        Used for loading in files outside of project view
    '''
    if ST2:
        return sublime.active_window().get_output_panel(name)
    else:
        return sublime.active_window().create_output_panel(name)


class CssStyleCompletion():
    def __init__(self, cache_path):
        self.cache_path = cache_path
        self.projects_cache = cache.load()

    def getProjectKeysOfView(self, view, return_both=False):
        if view.is_scratch():
            project_name = view.name()
        if not ST2:
            project_name = sublime.active_window().project_file_name()
        if ST2 or not project_name:
            # we could be ST3 but not in a true project
            # so fall back to using current folders opened within ST
            project_name = '-'.join(sublime.active_window().folders())

        css_extension = settings.get("css_extension")
        try:
            file_extension = os.path.splitext(view.file_name())[1]
        except:
            file_extension = os.path.splitext(view.name())[1]
        file_name = view.file_name()
        if not file_name:
            file_name = view.name()

        # if we have a project and we're working in a stand alone style file
        # return the project file name as the key
        if file_extension in css_extension and project_name:
            return (file_name, project_name)
        # if we are not overriding to get both keys
        # just return the file_name/file_key
        if not return_both:
            return (file_name, None)
        elif return_both and project_name:
            return (file_name, project_name)

    def returnPseudoCompletions(self):
        global pseudo_selector_list
        return [
            (selector + '\t pseudo selector', selector)
            for selector in pseudo_selector_list
        ]

    def returnSymbolCompletions(self, view, symbol_type):
        global symbol_dict, settings
        if not symbol_type in symbol_dict:
            return []
        file_key, project_key = self.getProjectKeysOfView(
            view,
            return_both=True
        )
        completion_list = []

        for file in get_external_files():
            if file in self.projects_cache:
                completion_list = completion_list + self.projects_cache[file][symbol_type][file]
        if file_key in self.projects_cache:
            if symbol_type in self.projects_cache[file_key]:
                completion_list = completion_list + self.projects_cache[file_key][symbol_type][file_key]
        if project_key in self.projects_cache:
            if symbol_type in self.projects_cache[project_key]:
                for file in self.projects_cache[project_key][symbol_type]:
                    completion_list = completion_list + self.projects_cache[project_key][symbol_type][file]
        if completion_list:
            return [
                tuple(completions)
                for completions in completion_list
            ]
        else:
            # we have no cache so just return whats in the current view
            return self.get_view_completions(view, symbol_dict[symbol_type])

    def get_view_completions(self, view, symbol_type):
        global symbol_dict
        if not symbol_type in symbol_dict:
            return []

        # get filename with extension
        try:
            file_name = os.path.basename(view.file_name())
        except:
            file_name = os.path.basename(view.name())
        symbols = view.find_by_selector(symbol_dict[symbol_type])
        results = []
        for point in symbols:
            completion = symbol_dict[symbol_type+'_command'](view, point, file_name)
            if completion is not None:
                results.extend(completion)
        return list(set(results))

    def _returnViewCompletions(self, view):
        results = []
        for view in sublime.active_window().views():
            results += self.get_view_completions(view, 'class')
        return list(set(results))

    def at_html_attribute(self, attribute, view, locations):
        selector = view.match_selector(locations[0], settings.get("html_attribute_scope"))
        if not selector:
            return False
        check_attribute = ''
        view_point = locations[0]
        char = ''
        selector_score = 1
        while((char != ' ' or selector_score != 0) and view_point > -1):
            char = view.substr(view_point)
            selector_score = view.score_selector(view_point, 'string')
            if(char != ' ' or selector_score != 0):
                check_attribute += char
            view_point -= 1
        check_attribute = check_attribute[::-1]
        if check_attribute.startswith(attribute):
                return True
        return False

    def at_style_symbol(self, style_symbol, style_scope, view, locations):
        selector = view.match_selector(locations[0], style_scope)
        if not selector:
            return False
        check_attribute = ''
        view_point = locations[0] - 1
        char = ''
        while(char != style_symbol and not re.match(r'[\n ]', char) and view_point > -1):
            char = view.substr(view_point)
            check_attribute += char
            view_point -= 1
        check_attribute = check_attribute[::-1]
        if check_attribute.startswith(style_symbol):
            return True
        return False


class CssStyleCompletionDeleteCacheCommand(sublime_plugin.WindowCommand):
    """Deletes all cache that plugin has created"""
    global cssStyleCompletion

    def run(self):
        cache.remove_cache()
        cssStyleCompletion.projects_cache = {}


class AddToCacheCommand(sublime_plugin.WindowCommand):
    def run(self, paths=[], name="", file_type="*.*"):
        import glob
        current_delay = 100
        for path in paths:
            if os.path.isdir(path):
                sublime.set_timeout(lambda: load_external_files(
                    glob.glob(path + os.path.sep + file_type),
                    as_scratch=False
                ), current_delay)
                current_delay = current_delay + 100


class CssStyleCompletionEvent(sublime_plugin.EventListener):
    global cssStyleCompletion, symbol_dict, settings

    def on_post_save(self, view):
        if not ST2:
            return
        cache.save_cache(view, cssStyleCompletion)

    def on_post_save_async(self, view):
        cache.save_cache(view, cssStyleCompletion)

    def on_query_completions(self, view, prefix, locations):
        # inside HTML scope completions
        if cssStyleCompletion.at_html_attribute('class', view, locations):
            return (cssStyleCompletion.returnSymbolCompletions(view, 'class'), sublime.INHIBIT_WORD_COMPLETIONS)
        if cssStyleCompletion.at_html_attribute('id', view, locations):
            return (cssStyleCompletion.returnSymbolCompletions(view, 'id'), sublime.INHIBIT_WORD_COMPLETIONS)

        # inside HTML with Emmet completions
        if settings.get("use_emmet"):
            if cssStyleCompletion.at_style_symbol('.', settings.get("emmet_scope"), view, locations):
                return (cssStyleCompletion.returnSymbolCompletions(view, 'class'), sublime.INHIBIT_WORD_COMPLETIONS)
            if cssStyleCompletion.at_style_symbol('#', settings.get("emmet_scope"), view, locations):
                return (cssStyleCompletion.returnSymbolCompletions(view, 'id'), sublime.INHIBIT_WORD_COMPLETIONS)

        # inside CSS scope pseudo completions
        if cssStyleCompletion.at_style_symbol(':', settings.get("css_completion_scope"), view, locations):
            return (cssStyleCompletion.returnPseudoCompletions(), sublime.INHIBIT_WORD_COMPLETIONS)

        # inside CSS scope symbol completions
        if cssStyleCompletion.at_style_symbol('.', settings.get("css_completion_scope"), view, locations):
            return (cssStyleCompletion.returnSymbolCompletions(view, 'class'), sublime.INHIBIT_WORD_COMPLETIONS)
        if cssStyleCompletion.at_style_symbol('#', settings.get("css_completion_scope"), view, locations):
            return (cssStyleCompletion.returnSymbolCompletions(view, 'id'), sublime.INHIBIT_WORD_COMPLETIONS)

        # inside LESS scope symbol completions
        if cssStyleCompletion.at_style_symbol(
            '@', 'source.less',
            view, locations
        ):
            return (
                cssStyleCompletion.returnSymbolCompletions(
                    view, 'less_var'
                ), sublime.INHIBIT_EXPLICIT_COMPLETIONS | sublime.INHIBIT_WORD_COMPLETIONS
            )

        if cssStyleCompletion.at_style_symbol(
            '.', 'source.less - parameter.less',
            view, locations
        ):
            return (
                cssStyleCompletion.returnSymbolCompletions(
                    view, 'less_mixin'
                ), sublime.INHIBIT_EXPLICIT_COMPLETIONS | sublime.INHIBIT_WORD_COMPLETIONS
            )

        # inside SCSS scope symbol completions
        if cssStyleCompletion.at_style_symbol(
            '$', 'source.scss, meta.property-value.scss',
            view, locations
        ):
            return (
                cssStyleCompletion.returnSymbolCompletions(
                    view, 'scss_var'
                ), sublime.INHIBIT_EXPLICIT_COMPLETIONS | sublime.INHIBIT_WORD_COMPLETIONS
            )

        if view.match_selector(
            locations[0],
            'meta.property-list.scss meta.at-rule.include.scss - punctuation.section.function.scss'
        ):
            return (
                cssStyleCompletion.returnSymbolCompletions(
                    view , 'scss_mixin'
                ), sublime.INHIBIT_EXPLICIT_COMPLETIONS | sublime.INHIBIT_WORD_COMPLETIONS
            )

        return None

if ST2:
    plugin_loaded()
