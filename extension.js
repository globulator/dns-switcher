import Clutter from 'gi://Clutter';
import Gio from 'gi://Gio';
import GLib from 'gi://GLib';
import GObject from 'gi://GObject';
import Pango from 'gi://Pango';
import St from 'gi://St';

import * as Main from 'resource:///org/gnome/shell/ui/main.js';
import * as PanelMenu from 'resource:///org/gnome/shell/ui/panelMenu.js';
import * as PopupMenu from 'resource:///org/gnome/shell/ui/popupMenu.js';
import { Spinner } from 'resource:///org/gnome/shell/ui/animation.js';
import { Extension } from 'resource:///org/gnome/shell/extensions/extension.js';

const DnsSwitcherIndicator = GObject.registerClass(
class DnsSwitcherIndicator extends PanelMenu.Button {
    _init(extension) {
        super._init(0.0, 'DNS Switcher');
        this.extension = extension;

        this._destroyed = false;
        this._cancellable = new Gio.Cancellable();
        this._probeProc = null;
        this._switching = false;
        this._netMonitorId = 0;
        this._netDebounceId = 0;

        // Path to backend python helper
        this._backendPath = GLib.build_filenamev([this.extension.path, 'dns_backend.py']);
        if (!GLib.file_test(this._backendPath, GLib.FileTest.EXISTS)) {
            throw new Error('DNS Switcher: dns_backend.py не найден в каталоге расширения');
        }

        this._domains = [];
        this._activeDomain = 'DEFAULT';
        this._categories = [
            { id: 'bypass', title: 'Антиблокировочные', icon: 'network-vpn-symbolic', domains: [] },
            { id: 'security', title: 'Защитные', icon: 'security-high-symbolic', domains: [] },
            { id: 'global', title: 'Глобальные', icon: 'globe-symbolic', domains: [] },
            { id: 'national', title: 'Национальные', icon: 'emoji-flags-symbolic', domains: [] },
        ];
        this._activeCategory = 'bypass';
        this._addCategory = 'bypass';
        this._tabButtons = new Map();
        this._targets = ['google.com', 'youtube.com', 'rutracker.org', 'discord.com'];
        this._activeTarget = 'google.com';
        this._isTargetsPanelOpen = false;
        this._latencies = {};
        this._isAddMode = false;
        this._searchQuery = '';
        this._sortMode = 'latency'; // 'latency' or 'name'
        this._rowWidgets = new Map();
        this._pendingDomains = new Set();
        this._animTimerId = null;
        this._dotFrameIndex = 0;

        this.add_style_class_name('dns-panel-button');

        // Top bar indicator container: icon + ubuntu spinner
        const panelBox = new St.BoxLayout({
            vertical: false,
            y_align: Clutter.ActorAlign.CENTER,
            x_align: Clutter.ActorAlign.CENTER,
        });

        this._panelIcon = new St.Icon({
            icon_name: 'preferences-system-network-symbolic',
            style_class: 'system-status-icon dns-icon-status',
        });
        panelBox.add_child(this._panelIcon);

        this._panelSpinner = new Spinner(16, { hideOnStop: true });
        this._panelSpinner.visible = false;
        panelBox.add_child(this._panelSpinner);

        this.add_child(panelBox);

        this._buildMenu();

        // Connect menu open event to auto-refresh latency & active DNS
        this.menu.connect('open-state-changed', (_menu, isOpen) => {
            if (isOpen) {
                this._onMenuOpened();
            } else {
                this._onMenuClosed();
            }
        });

        // Initial load
        this._loadInitialData();

        // Subscribe to network changes instead of a polling timer
        this._verifyActiveDns();
        this._netMonitorId = Gio.NetworkMonitor.get_default()
            .connect('network-changed', () => this._scheduleVerify());
    }

    _isCancelled(e) {
        return e instanceof GLib.Error && e.matches(Gio.IOErrorEnum, Gio.IOErrorEnum.CANCELLED);
    }

    _scheduleVerify() {
        if (this._netDebounceId) {
            GLib.Source.remove(this._netDebounceId);
            this._netDebounceId = 0;
        }
        this._netDebounceId = GLib.timeout_add_seconds(GLib.PRIORITY_DEFAULT, 2, () => {
            this._netDebounceId = 0;
            if (!this._destroyed) {
                this._verifyActiveDns();
            }
            return GLib.SOURCE_REMOVE;
        });
    }

    _setIndicatorStatus(status) {
        if (status === 'switching') {
            this._panelIcon.visible = false;
            this._panelSpinner.visible = true;
            this._panelSpinner.play();
        } else {
            this._panelSpinner.stop();
            this._panelSpinner.visible = false;
            this._panelIcon.visible = true;

            this._panelIcon.remove_style_class_name('dns-status-success');
            this._panelIcon.remove_style_class_name('dns-status-failed');
            this._panelIcon.remove_style_class_name('dns-status-default');

            if (status === 'success') {
                this._panelIcon.add_style_class_name('dns-status-success');
            } else if (status === 'failed') {
                this._panelIcon.add_style_class_name('dns-status-failed');
            } else {
                this._panelIcon.add_style_class_name('dns-status-default');
            }
        }
    }

    async _verifyActiveDns() {
        try {
            const res = await this._runBackendAsync(['verify-active']);
            if (this._destroyed) return;
            if (res && res.status) {
                this._setIndicatorStatus(res.status);
            }
        } catch (e) {
            if (!this._destroyed && !this._isCancelled(e)) {
                console.error('DNS Switcher: Failed to verify active DNS:', e);
            }
        }
    }

    _buildMenu() {
        const mainBox = new St.BoxLayout({
            style_class: 'dns-menu-box',
            vertical: true,
            x_expand: true,
        });

        // 1. Search Box with Sort Toggle Button
        const searchContainer = new St.BoxLayout({
            style_class: 'dns-search-container',
            vertical: false,
            x_expand: true,
            y_align: Clutter.ActorAlign.CENTER,
        });
        this._searchEntry = new St.Entry({
            style_class: 'dns-search-entry',
            hint_text: 'Поиск...',
            can_focus: true,
            x_expand: true,
        });
        const searchIcon = new St.Icon({
            icon_name: 'edit-find-symbolic',
            style_class: 'dns-search-icon',
        });
        this._searchEntry.set_primary_icon(searchIcon);

        this._searchEntry.clutter_text.connect('text-changed', () => {
            this._searchQuery = this._searchEntry.get_text().trim().toLowerCase();
            const isSearching = (this._searchQuery.length > 0);
            if (this._tabsBox) {
                this._tabsBox.visible = !isSearching;
            }
            this._applyView();
        });
        searchContainer.add_child(this._searchEntry);

        // Sort toggle button (latency <-> name)
        this._btnSortIcon = new St.Icon({
            icon_name: this._sortMode === 'latency' ? 'preferences-system-time-symbolic' : 'view-sort-ascending-symbolic',
            style_class: 'dns-btn-sort-icon',
            x_align: Clutter.ActorAlign.CENTER,
            y_align: Clutter.ActorAlign.CENTER,
            x_expand: true,
            y_expand: true,
        });
        this._btnSort = new St.Button({
            style_class: 'dns-btn-sort',
            child: this._btnSortIcon,
            can_focus: true,
            y_align: Clutter.ActorAlign.CENTER,
            accessible_name: 'Сортировка',
        });
        this._btnSort.connect('clicked', () => {
            this._sortMode = (this._sortMode === 'latency') ? 'name' : 'latency';
            this._btnSortIcon.icon_name = (this._sortMode === 'latency')
                ? 'preferences-system-time-symbolic'
                : 'view-sort-ascending-symbolic';
            this._applyView();
        });
        searchContainer.add_child(this._btnSort);

        mainBox.add_child(searchContainer);

        // Tab Bar with DNS Types (Anticensorship, Security, Global, National)
        this._tabsBox = new St.BoxLayout({
            style_class: 'dns-tabs-box',
            vertical: false,
            x_expand: true,
            y_align: Clutter.ActorAlign.CENTER,
        });
        this._renderTabs();
        mainBox.add_child(this._tabsBox);

        // 2. Add DNS Inline Row (hidden by default)
        this._addBox = new St.BoxLayout({
            style_class: 'dns-add-box',
            vertical: false,
            x_expand: true,
            y_align: Clutter.ActorAlign.CENTER,
            visible: false,
        });
        this._addEntry = new St.Entry({
            style_class: 'dns-add-entry',
            hint_text: 'Новый DNS-сервер...',
            can_focus: true,
            x_expand: true,
            y_align: Clutter.ActorAlign.CENTER,
        });
        this._addEntry.clutter_text.connect('key-press-event', (_actor, event) => {
            const symbol = event.get_key_symbol();
            if (symbol === Clutter.KEY_Return || symbol === Clutter.KEY_KP_Enter) {
                this._commitAdd();
                return Clutter.EVENT_STOP;
            } else if (symbol === Clutter.KEY_Escape) {
                this._cancelAdd();
                return Clutter.EVENT_STOP;
            }
            return Clutter.EVENT_PROPAGATE;
        });
        this._addBox.add_child(this._addEntry);

        // Category / Type cycle button
        this._addTypeIcon = new St.Icon({
            icon_name: this._getCategoryIcon(this._addCategory),
            style_class: 'dns-btn-add-type-icon',
            x_align: Clutter.ActorAlign.CENTER,
            y_align: Clutter.ActorAlign.CENTER,
        });
        this._btnAddType = new St.Button({
            style_class: 'dns-btn-add-type',
            child: this._addTypeIcon,
            can_focus: true,
            reactive: true,
            y_align: Clutter.ActorAlign.CENTER,
            accessible_name: 'Категория сервера',
        });
        this._btnAddType.connect('clicked', () => {
            this._cycleAddCategory();
        });
        this._addBox.add_child(this._btnAddType);

        // Apply button with check mark icon
        const addApplyIcon = new St.Icon({
            icon_name: 'emblem-ok-symbolic',
            style_class: 'dns-btn-add-apply-icon',
            x_align: Clutter.ActorAlign.CENTER,
            y_align: Clutter.ActorAlign.CENTER,
        });
        this._btnAddApply = new St.Button({
            style_class: 'dns-btn-add-apply',
            child: addApplyIcon,
            can_focus: true,
            reactive: true,
            y_align: Clutter.ActorAlign.CENTER,
            accessible_name: 'Сохранить сервер',
        });
        this._btnAddApply.connect('clicked', () => {
            this._commitAdd();
        });
        this._addBox.add_child(this._btnAddApply);

        mainBox.add_child(this._addBox);

        // 3. Scrollable List of Providers
        this._scrollView = new St.ScrollView({
            style_class: 'dns-scroll-view',
            hscrollbar_policy: St.PolicyType.NEVER,
            vscrollbar_policy: St.PolicyType.AUTOMATIC,
            x_expand: true,
        });
        this._listContainer = new St.BoxLayout({
            style_class: 'dns-list-container',
            vertical: true,
            x_expand: true,
        });
        this._scrollView.set_child(this._listContainer);
        mainBox.add_child(this._scrollView);

        // 4. Separator above Default DNS
        this._separator = new St.Widget({
            style_class: 'dns-separator',
            x_expand: true,
        });
        mainBox.add_child(this._separator);

        // 5. "DNS по умолчанию" Row Container
        this._defaultContainer = new St.BoxLayout({
            style_class: 'dns-list-container',
            vertical: true,
            x_expand: true,
        });
        mainBox.add_child(this._defaultContainer);

        // 5.5 Targets Dropdown Panel (hidden by default)
        this._targetsPanel = new St.BoxLayout({
            style_class: 'dns-targets-panel',
            vertical: true,
            x_expand: true,
            visible: false,
        });

        const targetsHeader = new St.BoxLayout({
            style_class: 'dns-targets-header',
            vertical: false,
            x_expand: true,
            y_align: Clutter.ActorAlign.CENTER,
        });
        const targetsTitle = new St.Label({
            text: 'Сервис проверки задержки:',
            style_class: 'dns-targets-title',
            x_expand: true,
            y_align: Clutter.ActorAlign.CENTER,
        });
        targetsHeader.add_child(targetsTitle);

        const closeBtn = new St.Button({
            style_class: 'dns-btn-trash',
            child: new St.Icon({
                icon_name: 'window-close-symbolic',
                style_class: 'dns-trash-icon',
            }),
            can_focus: true,
            y_align: Clutter.ActorAlign.CENTER,
            accessible_name: 'Закрыть панель целей',
        });
        closeBtn.connect('clicked', () => {
            this._toggleTargetsPanel(false);
        });
        targetsHeader.add_child(closeBtn);
        this._targetsPanel.add_child(targetsHeader);

        this._targetsListContainer = new St.BoxLayout({
            vertical: true,
            x_expand: true,
        });
        this._targetsPanel.add_child(this._targetsListContainer);

        const targetAddBox = new St.BoxLayout({
            style_class: 'dns-target-add-box',
            vertical: false,
            x_expand: true,
            y_align: Clutter.ActorAlign.CENTER,
        });
        this._targetAddEntry = new St.Entry({
            style_class: 'dns-target-add-entry',
            hint_text: 'Добавить (напр. x.com)...',
            can_focus: true,
            x_expand: true,
        });
        this._targetAddEntry.clutter_text.connect('key-press-event', (_actor, event) => {
            const symbol = event.get_key_symbol();
            if (symbol === Clutter.KEY_Return || symbol === Clutter.KEY_KP_Enter) {
                this._commitAddTarget();
                return Clutter.EVENT_STOP;
            }
            return Clutter.EVENT_PROPAGATE;
        });
        targetAddBox.add_child(this._targetAddEntry);

        const targetAddIcon = new St.Icon({
            icon_name: 'list-add-symbolic',
            style_class: 'dns-target-add-icon',
        });
        const targetAddBoxCenter = new St.BoxLayout({
            x_align: Clutter.ActorAlign.CENTER,
            y_align: Clutter.ActorAlign.CENTER,
            x_expand: true,
            y_expand: true,
        });
        targetAddBoxCenter.add_child(targetAddIcon);

        const btnAddTarget = new St.Button({
            style_class: 'dns-target-add-btn',
            child: targetAddBoxCenter,
            can_focus: true,
            y_align: Clutter.ActorAlign.CENTER,
            accessible_name: 'Добавить сервис проверки',
        });
        btnAddTarget.connect('clicked', () => {
            this._commitAddTarget();
        });
        targetAddBox.add_child(btnAddTarget);

        this._targetsPanel.add_child(targetAddBox);
        mainBox.add_child(this._targetsPanel);

        // 6. Bottom Action Bar
        const bottomBar = new St.BoxLayout({
            style_class: 'dns-bottom-bar',
            vertical: false,
            x_expand: true,
            y_align: Clutter.ActorAlign.CENTER,
        });

        this._btnAddIcon = new St.Icon({
            icon_name: 'list-add-symbolic',
            style_class: 'dns-plus-icon',
        });
        const btnAddCenter = new St.BoxLayout({
            x_align: Clutter.ActorAlign.CENTER,
            y_align: Clutter.ActorAlign.CENTER,
            x_expand: true,
            y_expand: true,
        });
        btnAddCenter.add_child(this._btnAddIcon);

        this._btnAdd = new St.Button({
            style_class: 'dns-btn-bottom',
            child: btnAddCenter,
            can_focus: true,
            y_align: Clutter.ActorAlign.CENTER,
            accessible_name: 'Добавить DNS',
        });
        this._btnAdd.connect('clicked', () => {
            if (this._isAddMode) {
                this._cancelAdd();
            } else {
                this._startAdd();
            }
        });
        bottomBar.add_child(this._btnAdd);

        const targetBtnBox = new St.BoxLayout({
            vertical: false,
            x_expand: true,
            x_align: Clutter.ActorAlign.CENTER,
            y_align: Clutter.ActorAlign.CENTER,
        });
        const targetIcon = new St.Icon({
            icon_name: 'applications-internet-symbolic',
            style_class: 'dns-target-icon',
        });
        targetBtnBox.add_child(targetIcon);

        this._targetLabel = new St.Label({
            text: this._activeTarget,
            style_class: 'dns-target-label',
            y_align: Clutter.ActorAlign.CENTER,
        });
        targetBtnBox.add_child(this._targetLabel);

        this._targetArrow = new St.Icon({
            icon_name: 'pan-down-symbolic',
            style_class: 'dns-target-arrow',
            y_align: Clutter.ActorAlign.CENTER,
        });
        targetBtnBox.add_child(this._targetArrow);

        this._btnTarget = new St.Button({
            style_class: 'dns-btn-target',
            child: targetBtnBox,
            can_focus: true,
            x_expand: true,
            y_align: Clutter.ActorAlign.CENTER,
            accessible_name: 'Выбор цели проверки',
        });
        this._btnTarget.connect('clicked', () => {
            this._toggleTargetsPanel();
        });
        bottomBar.add_child(this._btnTarget);

        this._btnRefreshIcon = new St.Icon({
            icon_name: 'view-refresh-symbolic',
            style_class: 'dns-btn-bottom-icon',
        });
        const btnRefreshCenter = new St.BoxLayout({
            x_align: Clutter.ActorAlign.CENTER,
            y_align: Clutter.ActorAlign.CENTER,
            x_expand: true,
            y_expand: true,
        });
        btnRefreshCenter.add_child(this._btnRefreshIcon);

        this._btnRefresh = new St.Button({
            style_class: 'dns-btn-bottom',
            child: btnRefreshCenter,
            can_focus: true,
            y_align: Clutter.ActorAlign.CENTER,
            accessible_name: 'Обновить задержки',
        });
        this._btnRefresh.connect('clicked', () => {
            this._refreshLatencies();
        });
        bottomBar.add_child(this._btnRefresh);

        this._btnDonateIcon = new St.Icon({
            icon_name: 'emblem-favorite-symbolic',
            style_class: 'dns-btn-bottom-icon dns-donate-icon',
        });
        const btnDonateCenter = new St.BoxLayout({
            x_align: Clutter.ActorAlign.CENTER,
            y_align: Clutter.ActorAlign.CENTER,
            x_expand: true,
            y_expand: true,
        });
        btnDonateCenter.add_child(this._btnDonateIcon);

        this._btnDonate = new St.Button({
            style_class: 'dns-btn-bottom dns-btn-donate',
            child: btnDonateCenter,
            can_focus: true,
            y_align: Clutter.ActorAlign.CENTER,
            accessible_name: 'Поддержать автора (Boosty)',
        });
        this._btnDonate.connect('clicked', () => {
            this._openUrl('https://boosty.to/globulator/donate');
            this.menu.close();
        });
        bottomBar.add_child(this._btnDonate);

        mainBox.add_child(bottomBar);

        const menuItem = new PopupMenu.PopupBaseMenuItem({
            reactive: false,
            can_focus: false,
            style_class: 'dns-popup-menu-item',
        });
        menuItem.add_child(mainBox);
        this.menu.addMenuItem(menuItem);
    }

    _openUrl(url) {
        try {
            const context = global.create_app_launch_context ? global.create_app_launch_context(0, -1) : null;
            Gio.AppInfo.launch_default_for_uri(url, context);
        } catch (err) {
            console.error(`DNS Switcher: не удалось открыть ссылку ${url}:`, err);
        }
    }

    _runBackendAsync(args) {
        return new Promise((resolve, reject) => {
            try {
                const proc = Gio.Subprocess.new(
                    ['python3', this._backendPath, ...args],
                    Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_PIPE
                );
                proc.communicate_utf8_async(null, this._cancellable, (p, res) => {
                    try {
                        const [, stdout, stderr] = p.communicate_utf8_finish(res);
                        let data = null;
                        try { data = JSON.parse(stdout); } catch (_e) { /* not JSON */ }
                        if (!p.get_successful()) {
                            throw new Error((data && data.error) || stderr || 'Subprocess error');
                        }
                        if (data === null) {
                            throw new Error('Bad JSON from backend');
                        }
                        resolve(data);
                    } catch (e) {
                        reject(e);
                    }
                });
            } catch (e) {
                reject(e);
            }
        });
    }

    _streamBackend(args, onLine, onFinish) {
        let proc;
        try {
            proc = Gio.Subprocess.new(
                ['python3', this._backendPath, ...args],
                Gio.SubprocessFlags.STDOUT_PIPE | Gio.SubprocessFlags.STDERR_SILENCE
            );
        } catch (e) {
            console.error('DNS Switcher: Stream error:', e);
            if (onFinish) onFinish();
            return null;
        }

        const stdoutStream = new Gio.DataInputStream({
            base_stream: proc.get_stdout_pipe()
        });

        const readNextLine = () => {
            stdoutStream.read_line_async(GLib.PRIORITY_DEFAULT, this._cancellable, (stream, res) => {
                if (this._destroyed) return;
                let lineBytes = null;
                try {
                    [lineBytes] = stream.read_line_finish_utf8(res);
                } catch (_e) {
                    /* cancelled / interrupted */
                }
                if (lineBytes === null) {
                    if (onFinish) onFinish();
                    return;
                }
                const line = lineBytes.trim();
                if (line) {
                    try {
                        const data = JSON.parse(line);
                        if (onLine) onLine(data);
                    } catch (e) {
                        console.error('DNS Switcher: Parse error:', e);
                    }
                }
                readNextLine();
            });
        };

        readNextLine();
        return proc;
    }

    _startDotsAnimation(domains) {
        const DOT_FRAMES = ['.', '..', '...'];

        for (const domain of domains) {
            this._pendingDomains.add(domain);
            const widgets = this._rowWidgets.get(domain);
            if (widgets && widgets.latencyLabel) {
                widgets.latencyLabel.set_text('.');
                widgets.latencyLabel.style_class = 'dns-latency-checking';
            }
        }

        if (this._animTimerId === null && this._pendingDomains.size > 0) {
            this._dotFrameIndex = 0;
            this._animTimerId = GLib.timeout_add(GLib.PRIORITY_DEFAULT, 260, () => {
                this._dotFrameIndex = (this._dotFrameIndex + 1) % DOT_FRAMES.length;
                const frameText = DOT_FRAMES[this._dotFrameIndex];
                for (const domain of this._pendingDomains) {
                    const widgets = this._rowWidgets.get(domain);
                    if (widgets && widgets.latencyLabel) {
                        widgets.latencyLabel.set_text(frameText);
                    }
                }
                return GLib.SOURCE_CONTINUE;
            });
        }
    }

    _stopDotsAnimationFor(domain, data) {
        this._pendingDomains.delete(domain);
        const widgets = this._rowWidgets.get(domain);
        if (widgets && widgets.latencyLabel) {
            if (data.ok) {
                widgets.latencyLabel.set_text(`${data.latency} ms`);
                widgets.latencyLabel.style_class = 'dns-latency-ok';
            } else {
                widgets.latencyLabel.set_text(data.text || 'не отвечает');
                widgets.latencyLabel.style_class = 'dns-latency-error';
            }
            if (widgets.protoBadge && data.proto) {
                const protoUpper = data.proto.toUpperCase();
                widgets.protoBadge.text = protoUpper;
                if (protoUpper === 'DOT') {
                    widgets.protoBadge.style_class = 'dns-badge-dot';
                } else if (protoUpper === 'DOH') {
                    widgets.protoBadge.style_class = 'dns-badge-doh';
                } else {
                    widgets.protoBadge.style_class = 'dns-badge-udp';
                }
            }
        }

        if (this._pendingDomains.size === 0) {
            this._stopAllDotsAnimation();
        }
    }

    _stopAllDotsAnimation() {
        if (this._animTimerId !== null) {
            GLib.Source.remove(this._animTimerId);
            this._animTimerId = null;
        }
        this._pendingDomains.clear();
    }

    _getCategoryIcon(catId) {
        const cat = this._categories.find(c => c.id === catId);
        if (cat && cat.icon) return cat.icon;
        switch (catId) {
            case 'bypass': return 'network-vpn-symbolic';
            case 'security': return 'security-high-symbolic';
            case 'global': return 'globe-symbolic';
            case 'national': return 'emoji-flags-symbolic';
            default: return 'network-vpn-symbolic';
        }
    }

    _renderTabs() {
        if (!this._tabsBox) return;
        this._tabsBox.destroy_all_children();
        this._tabButtons.clear();

        for (const cat of this._categories) {
            const isActive = (cat.id === this._activeCategory);
            const icon = new St.Icon({
                icon_name: cat.icon,
                style_class: 'dns-tab-icon',
                x_align: Clutter.ActorAlign.CENTER,
                y_align: Clutter.ActorAlign.CENTER,
                x_expand: true,
                y_expand: true,
            });

            const btn = new St.Button({
                style_class: isActive ? 'dns-tab-btn active' : 'dns-tab-btn',
                child: icon,
                can_focus: true,
                x_expand: true,
                y_align: Clutter.ActorAlign.CENTER,
                accessible_name: cat.title,
            });

            btn.connect('clicked', () => {
                this._selectCategory(cat.id);
            });

            this._tabButtons.set(cat.id, btn);
            this._tabsBox.add_child(btn);
        }
    }

    _selectCategory(catId) {
        if (this._activeCategory === catId) return;
        this._activeCategory = catId;
        this._updateTabHighlights();
        this._applyView();
    }

    _updateTabHighlights() {
        for (const [id, btn] of this._tabButtons.entries()) {
            if (id === this._activeCategory) {
                btn.add_style_class_name('active');
            } else {
                btn.remove_style_class_name('active');
            }
        }
    }

    _cycleAddCategory() {
        const catIds = this._categories.map(c => c.id);
        if (!catIds.length) return;
        const currentIndex = catIds.indexOf(this._addCategory);
        const nextIndex = (currentIndex + 1) % catIds.length;
        this._addCategory = catIds[nextIndex];
        this._updateAddTypeButton();
    }

    _updateAddTypeButton() {
        if (this._addTypeIcon) {
            this._addTypeIcon.icon_name = this._getCategoryIcon(this._addCategory);
        }
    }

    async _loadInitialData() {
        try {
            const d = await this._runBackendAsync(['init']);
            if (this._destroyed) return;
            if (Array.isArray(d.categories)) {
                this._categories = d.categories;
                this._renderTabs();
            }
            if (Array.isArray(d.domains)) {
                this._domains = d.domains;
            }
            if (Array.isArray(d.targets)) {
                this._targets = d.targets;
            }
            this._activeTarget = d.active_target || this._targets[0];
            if (this._targetLabel) {
                this._targetLabel.set_text(this._activeTarget);
            }
            this._latencies = d.cached || {};
            this._activeDomain = (d.active && !d.active.is_default) ? d.active.domain : 'DEFAULT';
            this._rebuildRows();
        } catch (e) {
            if (!this._isCancelled(e)) {
                console.error('DNS Switcher: init failed:', e);
            }
        }
    }

    async _onMenuOpened() {
        this._searchEntry.set_text('');
        this._searchQuery = '';
        if (this._tabsBox) {
            this._tabsBox.visible = true;
        }
        this._cancelAdd();
        this._toggleTargetsPanel(false);

        // Immediately refresh active DNS state
        try {
            const activeData = await this._runBackendAsync(['get-active']);
            if (this._destroyed) return;
            if (activeData && activeData.domain) {
                this._activeDomain = activeData.is_default ? 'DEFAULT' : activeData.domain;
                this._updateActiveHighlights();
            }
        } catch (e) {
            if (!this._isCancelled(e)) {
                console.error('DNS Switcher: Error updating active state on open:', e);
            }
        }

        this._verifyActiveDns();
        this._refreshLatencies();
    }

    _onMenuClosed() {
        this._searchEntry.set_text('');
        this._searchQuery = '';
        if (this._tabsBox) {
            this._tabsBox.visible = true;
        }
        this._cancelAdd();
        this._toggleTargetsPanel(false);
        this._stopAllDotsAnimation();
    }

    _toggleTargetsPanel(forceState) {
        const nextState = (forceState !== undefined) ? forceState : !this._isTargetsPanelOpen;
        this._isTargetsPanelOpen = nextState;
        this._targetsPanel.visible = nextState;
        this._targetArrow.icon_name = nextState ? 'pan-up-symbolic' : 'pan-down-symbolic';
        if (nextState) {
            this._btnTarget.add_style_class_name('active');
            this._renderTargetsList();
        } else {
            this._btnTarget.remove_style_class_name('active');
        }
    }

    _renderTargetsList() {
        this._targetsListContainer.destroy_all_children();

        for (const target of this._targets) {
            const isSelected = (target === this._activeTarget);

            const rowBox = new St.BoxLayout({
                style_class: isSelected ? 'dns-target-row active' : 'dns-target-row',
                vertical: false,
                reactive: true,
                track_hover: true,
                x_expand: true,
                y_align: Clutter.ActorAlign.CENTER,
            });

            const contentBtn = new St.Button({
                style_class: 'dns-target-content',
                can_focus: true,
                x_expand: true,
                y_align: Clutter.ActorAlign.CENTER,
                accessible_name: `Выбрать цель ${target}`,
            });

            const contentBox = new St.BoxLayout({
                vertical: false,
                x_expand: true,
                y_align: Clutter.ActorAlign.CENTER,
            });

            const radioBin = new St.Bin({
                style_class: isSelected ? 'dns-radio active' : 'dns-radio',
                x_align: Clutter.ActorAlign.CENTER,
                y_align: Clutter.ActorAlign.CENTER,
            });
            const radioDot = new St.Widget({
                style_class: 'dns-radio-dot',
                visible: isSelected,
            });
            radioBin.set_child(radioDot);
            contentBox.add_child(radioBin);

            const label = new St.Label({
                text: target,
                style_class: 'dns-target-item-label',
                x_expand: true,
                y_align: Clutter.ActorAlign.CENTER,
            });
            contentBox.add_child(label);

            contentBtn.set_child(contentBox);
            contentBtn.connect('clicked', () => {
                this._selectTarget(target);
            });
            rowBox.add_child(contentBtn);

            if (this._targets.length > 1) {
                const trashBtn = new St.Button({
                    style_class: 'dns-btn-trash',
                    child: new St.Icon({
                        icon_name: 'user-trash-symbolic',
                        style_class: 'dns-trash-icon',
                    }),
                    can_focus: true,
                    reactive: true,
                    y_align: Clutter.ActorAlign.CENTER,
                    accessible_name: `Удалить цель ${target}`,
                });
                trashBtn.connect('clicked', () => {
                    this._removeTarget(target);
                });
                rowBox.add_child(trashBtn);
            }

            this._targetsListContainer.add_child(rowBox);
        }
    }

    async _selectTarget(target) {
        if (this._activeTarget === target) {
            this._toggleTargetsPanel(false);
            return;
        }

        this._activeTarget = target;
        this._targetLabel.set_text(target);
        this._toggleTargetsPanel(false);

        try {
            await this._runBackendAsync(['targets-set', target]);
        } catch (e) {
            if (!this._isCancelled(e)) {
                console.error('DNS Switcher: Failed to set target in backend:', e);
            }
        }

        this._refreshLatencies();
    }

    async _commitAddTarget() {
        const text = this._targetAddEntry.get_text().trim();
        if (text) {
            try {
                const res = await this._runBackendAsync(['targets-add', text]);
                if (this._destroyed) return;
                if (res && res.targets) {
                    this._targets = res.targets;
                    this._activeTarget = res.active || text;
                    this._targetLabel.set_text(this._activeTarget);
                }
            } catch (e) {
                if (!this._isCancelled(e)) {
                    console.error('DNS Switcher: Failed to add target:', e);
                    Main.notifyError('DNS Switcher', e.message);
                }
            }
            this._targetAddEntry.set_text('');
            this._toggleTargetsPanel(false);
            this._refreshLatencies();
        }
    }

    async _removeTarget(target) {
        this._targets = this._targets.filter(t => t !== target);
        if (this._activeTarget === target) {
            this._activeTarget = this._targets[0] || 'google.com';
            this._targetLabel.set_text(this._activeTarget);
        }
        this._renderTargetsList();

        try {
            const res = await this._runBackendAsync(['targets-remove', target]);
            if (this._destroyed) return;
            if (res && res.targets) {
                this._targets = res.targets;
                if (res.active) {
                    this._activeTarget = res.active;
                    this._targetLabel.set_text(this._activeTarget);
                }
            }
        } catch (e) {
            if (!this._isCancelled(e)) {
                console.error('DNS Switcher: Failed to remove target:', e);
            }
        }
    }

    _refreshLatencies() {
        if (this._probeProc) {
            this._probeProc.force_exit();
            this._probeProc = null;
        }
        this._startDotsAnimation([...this._domains, 'DEFAULT']);

        const proc = this._streamBackend(
            ['probe-stream', this._activeTarget],
            (data) => {
                if (proc !== this._probeProc || !data || !data.domain) return;
                this._latencies[data.domain] = data;
                this._stopDotsAnimationFor(data.domain, data);
            },
            () => {
                if (proc !== this._probeProc) return;
                this._probeProc = null;
                this._stopAllDotsAnimation();
                if (this._sortMode === 'latency') {
                    this._applyView();
                }
            }
        );
        this._probeProc = proc;
        if (!proc) this._stopAllDotsAnimation();
    }

    _getSortedDomains(sourceList) {
        const list = [...(sourceList || this._domains)];
        if (this._sortMode === 'name') {
            list.sort((a, b) => a.localeCompare(b));
        } else {
            list.sort((a, b) => {
                const latA = this._latencies[a];
                const latB = this._latencies[b];

                const valA = (latA && latA.ok && typeof latA.latency === 'number') ? latA.latency : 999999;
                const valB = (latB && latB.ok && typeof latB.latency === 'number') ? latB.latency : 999999;

                if (valA !== valB) {
                    return valA - valB;
                }
                return a.localeCompare(b);
            });
        }
        return list;
    }

    _rebuildRows() {
        this._rowWidgets.clear();
        this._listContainer.destroy_all_children();
        this._defaultContainer.destroy_all_children();

        for (const domain of this._domains) {
            this._listContainer.add_child(this._createRowWidget(domain, false));
        }
        this._defaultContainer.add_child(this._createRowWidget('DEFAULT', true));

        this._applyView();
    }

    _applyView() {
        const q = this._searchQuery;
        const cat = this._categories.find(c => c.id === this._activeCategory);
        const inCat = new Set(cat ? (cat.domains || []) : this._domains);

        this._getSortedDomains(this._domains).forEach((d, i) => {
            const w = this._rowWidgets.get(d);
            if (!w) return;
            w.button.visible = q ? d.toLowerCase().includes(q) : inCat.has(d);
            this._listContainer.set_child_at_index(w.button, i);
        });

        const def = this._rowWidgets.get('DEFAULT');
        if (def) {
            def.button.visible = !q || 'dns по умолчанию'.includes(q) || 'default'.includes(q);
        }

        this._updateActiveHighlights();
    }

    _createRowWidget(domain, isDefault) {
        const rowBox = new St.BoxLayout({
            style_class: 'dns-row',
            vertical: false,
            reactive: true,
            track_hover: true,
            x_expand: true,
            y_align: Clutter.ActorAlign.CENTER,
        });

        const contentButton = new St.Button({
            style_class: 'dns-row-content',
            can_focus: true,
            x_expand: true,
            y_align: Clutter.ActorAlign.CENTER,
            accessible_name: isDefault ? 'DNS по умолчанию' : domain,
        });

        const contentBox = new St.BoxLayout({
            vertical: false,
            x_expand: true,
            y_align: Clutter.ActorAlign.CENTER,
        });

        const radioBin = new St.Bin({
            style_class: 'dns-radio',
            x_align: Clutter.ActorAlign.CENTER,
            y_align: Clutter.ActorAlign.CENTER,
        });
        const radioDot = new St.Widget({
            style_class: 'dns-radio-dot',
            visible: false,
        });
        radioBin.set_child(radioDot);
        contentBox.add_child(radioBin);

        if (isDefault) {
            const globeIcon = new St.Icon({
                icon_name: 'network-wired-symbolic',
                style_class: 'dns-default-icon',
            });
            contentBox.add_child(globeIcon);
        }

        const titleText = isDefault ? 'DNS по умолчанию' : domain;
        const domainLabel = new St.Label({
            text: titleText,
            style_class: 'dns-domain-label',
            x_expand: true,
            y_align: Clutter.ActorAlign.CENTER,
        });
        domainLabel.clutter_text.ellipsize = Pango.EllipsizeMode.END;
        contentBox.add_child(domainLabel);

        let protoBadge = null;
        if (!isDefault) {
            const cached = this._latencies[domain];
            let protoText = 'UDP';
            let protoClass = 'dns-badge-udp';
            if (cached && cached.proto) {
                protoText = cached.proto.toUpperCase();
                if (protoText === 'DOT') {
                    protoClass = 'dns-badge-dot';
                } else if (protoText === 'DOH') {
                    protoClass = 'dns-badge-doh';
                } else {
                    protoClass = 'dns-badge-udp';
                }
            } else if (domain.includes('dns-ai') || domain.includes('dot')) {
                protoText = 'DoT';
                protoClass = 'dns-badge-dot';
            }
            protoBadge = new St.Label({
                text: protoText,
                style_class: protoClass,
                y_align: Clutter.ActorAlign.CENTER,
            });
            contentBox.add_child(protoBadge);
        }

        const cached = this._latencies[domain];
        let latencyText = '.';
        let latencyClass = 'dns-latency-checking';
        if (cached) {
            if (cached.ok) {
                latencyText = `${cached.latency} ms`;
                latencyClass = 'dns-latency-ok';
            } else {
                latencyText = cached.text || 'не отвечает';
                latencyClass = 'dns-latency-error';
            }
        }
        const latencyLabel = new St.Label({
            text: latencyText,
            style_class: latencyClass,
            y_align: Clutter.ActorAlign.CENTER,
        });
        contentBox.add_child(latencyLabel);

        contentButton.set_child(contentBox);

        contentButton.connect('clicked', () => {
            this._selectDomain(domain);
        });

        rowBox.add_child(contentButton);

        if (!isDefault) {
            const trashIcon = new St.Icon({
                icon_name: 'user-trash-symbolic',
                style_class: 'dns-trash-icon',
            });
            const trashBtn = new St.Button({
                style_class: 'dns-btn-trash',
                child: trashIcon,
                can_focus: true,
                reactive: true,
                y_align: Clutter.ActorAlign.CENTER,
                accessible_name: `Удалить сервер ${domain}`,
            });
            trashBtn.connect('clicked', () => {
                this._removeDomain(domain);
            });
            rowBox.add_child(trashBtn);
        }

        this._rowWidgets.set(domain, {
            button: rowBox,
            contentButton,
            radio: radioBin,
            dot: radioDot,
            protoBadge,
            latencyLabel,
            domainLabel,
            isDefault,
        });

        return rowBox;
    }

    _updateActiveHighlights() {
        for (const [domain, widgets] of this._rowWidgets.entries()) {
            const isActive = (domain === this._activeDomain);
            if (isActive) {
                widgets.button.add_style_class_name('active');
                widgets.radio.add_style_class_name('active');
                widgets.dot.show();
            } else {
                widgets.button.remove_style_class_name('active');
                widgets.radio.remove_style_class_name('active');
                widgets.dot.hide();
            }
        }
    }

    async _selectDomain(domain) {
        if (this._switching) return;
        this._switching = true;
        const prev = this._activeDomain;
        this._activeDomain = domain;
        this._updateActiveHighlights();
        this._setIndicatorStatus('switching');

        try {
            const res = await this._runBackendAsync(['set', domain]);
            if (this._destroyed) return;
            if (!res || !res.success) {
                throw new Error((res && res.error) || 'Unknown error');
            }
            const v = await this._runBackendAsync(['verify-active']);
            if (this._destroyed) return;
            this._setIndicatorStatus((v && v.status) || (domain === 'DEFAULT' ? 'default' : 'success'));
        } catch (e) {
            if (this._destroyed || this._isCancelled(e)) return;
            this._activeDomain = prev;
            this._updateActiveHighlights();
            this._setIndicatorStatus('failed');
            Main.notifyError('DNS Switcher', e.message);
        } finally {
            this._switching = false;
        }
    }

    _startAdd() {
        this._isAddMode = true;
        this._addBox.show();
        this._addCategory = this._activeCategory || 'bypass';
        this._updateAddTypeButton();
        this._addEntry.set_text('');
        this._addEntry.grab_key_focus();
        this._btnAddIcon.icon_name = 'window-close-symbolic';
    }

    _cancelAdd() {
        this._isAddMode = false;
        this._addBox.hide();
        this._addEntry.set_text('');
        this._btnAddIcon.icon_name = 'list-add-symbolic';
    }

    async _commitAdd() {
        const text = this._addEntry.get_text().trim();
        if (text) {
            const targetCat = this._addCategory;
            try {
                const res = await this._runBackendAsync(['add', text, targetCat]);
                if (this._destroyed) return;
                if (res && res.success) {
                    if (Array.isArray(res.categories)) {
                        this._categories = res.categories;
                    }
                    if (Array.isArray(res.domains)) {
                        this._domains = res.domains;
                    }
                    this._activeCategory = targetCat;
                    this._updateTabHighlights();
                    this._rebuildRows();
                    this._probeSingle(res.domain || text);
                } else if (res && res.error) {
                    Main.notifyError('DNS Switcher', res.error);
                }
            } catch (e) {
                if (!this._isCancelled(e)) {
                    console.error('DNS Switcher: Failed to add domain:', e);
                    Main.notifyError('DNS Switcher', e.message);
                }
            }
        }
        this._cancelAdd();
    }

    async _probeSingle(domain) {
        this._startDotsAnimation([domain]);
        try {
            const data = await this._runBackendAsync(['probe-single', domain, this._activeTarget]);
            if (this._destroyed) return;
            if (data && data.domain) {
                this._latencies[domain] = data;
                this._stopDotsAnimationFor(domain, data);
            } else {
                this._stopDotsAnimationFor(domain, { ok: false, text: 'ошибка' });
            }
        } catch (e) {
            if (!this._isCancelled(e)) {
                console.error('DNS Switcher: Single probe failed:', e);
                this._stopDotsAnimationFor(domain, { ok: false, text: 'ошибка' });
            }
        }
    }

    async _removeDomain(domain) {
        for (const cat of this._categories) {
            if (cat.domains) {
                cat.domains = cat.domains.filter(d => d !== domain);
            }
        }
        this._domains = this._domains.filter(d => d !== domain);
        if (this._activeDomain === domain) {
            await this._selectDomain('DEFAULT');
        }
        this._rebuildRows();

        try {
            const res = await this._runBackendAsync(['remove', domain]);
            if (this._destroyed) return;
            if (res && res.success) {
                if (Array.isArray(res.categories)) {
                    this._categories = res.categories;
                }
                if (Array.isArray(res.domains)) {
                    this._domains = res.domains;
                }
            }
        } catch (e) {
            if (!this._isCancelled(e)) {
                console.error('DNS Switcher: Failed to remove domain:', e);
            }
        }
    }

    destroy() {
        this._destroyed = true;
        this._cancellable.cancel();
        if (this._probeProc) {
            this._probeProc.force_exit();
            this._probeProc = null;
        }
        if (this._netMonitorId) {
            Gio.NetworkMonitor.get_default().disconnect(this._netMonitorId);
            this._netMonitorId = 0;
        }
        if (this._netDebounceId) {
            GLib.Source.remove(this._netDebounceId);
            this._netDebounceId = 0;
        }
        this._stopAllDotsAnimation();
        this._rowWidgets.clear();
        super.destroy();
    }
});

export default class DnsSwitcherExtension extends Extension {
    enable() {
        this._indicator = new DnsSwitcherIndicator(this);
        Main.panel.addToStatusArea(this.uuid, this._indicator);
    }

    disable() {
        if (this._indicator) {
            this._indicator.destroy();
            this._indicator = null;
        }
    }
}
