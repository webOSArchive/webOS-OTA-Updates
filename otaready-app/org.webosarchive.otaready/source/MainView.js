/*
 * MainView: OTA Ready v2 (webOS CE 3.1.0 onward).
 *
 * Shows what the root daemon last found (/media/internal/.otaready/status.json):
 * this device's build, whether an update is offered, and if not, why. Installing
 * happens in System Updates, which this package patches to use the community
 * server; this app is the place to see the state and to send device details.
 *
 * UI follows the first-party Settings idiom (cf. com.palm.app.dateandtime):
 * enyo-toolbar-light "header-welcome" bar, a Scroller with a 500px box-center
 * column of captioned RowGroups, a bottom Toolbar. No emoji (2011 WebKit has no
 * colour-emoji font). Plain XMLHttpRequest + JSON.parse: this Enyo build's
 * enyo.xhr/enyo.json have an incompatible signature and throw during create().
 */
enyo.kind({
    name: "MainView",
    kind: "VFlexBox",
    className: "otaready enyo-bg",

    statusUrl: "file:///media/internal/.otaready/status.json",
    diagUrl: "file:///media/internal/.otaready/diagnostics.txt",
    curatorEmail: "curator@webosarchive.org",
    docsUrl: "https://docs.webosarchive.org",

    components: [
        { kind: "Control", className: "enyo-toolbar-light header-welcome", components: [
            { kind: "Image", src: "images/header-icon-otaready.png" },
            { content: "OTA Ready", style: "padding-left: 10px;" }
        ]},
        { kind: "Scroller", flex: 1, components: [
            { kind: "VFlexBox", className: "box-center", components: [
                { kind: "RowGroup", caption: "Status", components: [
                    { kind: "Item", tapHighlight: false, layoutKind: "HFlexLayout", align: "center", components: [
                        { name: "spinner", kind: "Spinner", showing: true },
                        { name: "statusText", flex: 1, className: "otaready-status", content: "Checking…" }
                    ]}
                ]},
                { name: "adviceGroup", kind: "RowGroup", caption: "What To Do", showing: false, components: [
                    { kind: "Item", tapHighlight: false, onclick: "adviceTap", components: [
                        { name: "adviceText", className: "otaready-advice", allowHtml: true }
                    ]}
                ]},
                { name: "detailGroup", kind: "RowGroup", caption: "Device Details", showing: false, components: [
                    { kind: "Item", tapHighlight: false, layoutKind: "HFlexLayout", components: [
                        { flex: 1, content: "Version" },
                        { name: "valVersion", className: "otaready-value" }
                    ]},
                    { kind: "Item", tapHighlight: false, layoutKind: "HFlexLayout", components: [
                        { flex: 1, content: "Build" },
                        { name: "valBuild", className: "otaready-value" }
                    ]},
                    // The NDUID is what an owner sends to be added to a rollout
                    // (the update server's device filter); Save Device Details
                    // writes it to a file too.
                    { kind: "Item", tapHighlight: false, components: [
                        { content: "Device ID (NDUID)" },
                        { name: "valNduid", className: "otaready-patch-list" }
                    ]},
                    { name: "checkedRow", kind: "Item", tapHighlight: false, layoutKind: "HFlexLayout", components: [
                        { flex: 1, content: "Last check" },
                        { name: "valChecked", className: "otaready-value" }
                    ]}
                ]}
            ]}
        ]},
        { kind: "Toolbar", className: "enyo-toolbar-light", pack: "center", align: "center", components: [
            { name: "checkBtn", kind: "Button", caption: "Check Again", onclick: "doCheck" },
            { name: "openBtn", kind: "Button", className: "enyo-button-affirmative",
              caption: "Open System Updates", onclick: "openUpdates" }
        ]},
        { name: "trigger", kind: "PalmService",
          service: "palm://org.webosarchive.otaready.service/", method: "trigger",
          onFailure: "onTriggerFail" },
        { kind: "AppMenu", components: [
            { caption: "Save Device Details", onclick: "doSaveDetails" },
            { caption: "Send Device Details", onclick: "doSendDetails" }
        ]},
        { name: "appManager", kind: "PalmService",
          service: "palm://com.palm.applicationManager/", method: "open" },
        { name: "launcher", kind: "PalmService",
          service: "palm://com.palm.applicationManager/", method: "launch" },
        { name: "saveSvc", kind: "PalmService",
          service: "palm://org.webosarchive.otaready.service/", method: "saveDetails",
          onSuccess: "onSaveOk", onFailure: "onSaveFail" },
        // App Museum II self-update helper (title must be "OTA Ready").
        { name: "otaUpdater", kind: "Helpers.Updater" }
    ],

    create: function() {
        this.inherited(arguments);
        this.load();
        this.$.otaUpdater.CheckForUpdate("OTA Ready");
    },

    // Read what the daemon last wrote, without asking it to check.
    load: function() {
        var self = this;
        this.fetchJson(this.statusUrl, function(s) {
            if (!s) { self.onError(); return; }
            self.lastStatus = s;
            self.render(s);
        });
    },

    // Ask the daemon to check now, then wait (up to 45 s) for a newer status.json.
    doCheck: function() {
        var before = (this.lastStatus && this.lastStatus.time) || 0;
        this.busy("Checking with the update server…");
        this.waits = 0;
        this.$.trigger.call({ cmd: "check" });
        this.waitForStatus(before);
    },

    waitForStatus: function(before) {
        var self = this;
        this.fetchJson(this.statusUrl, function(s) {
            if ((!s || s.time == before) && self.waits < 45) {
                self.waits++;
                setTimeout(function() { self.waitForStatus(before); }, 1000);
                return;
            }
            if (!s) { self.onError(); return; }
            self.lastStatus = s;
            self.render(s);
        });
    },

    busy: function(text) {
        this.$.spinner.show();
        this.$.statusText.removeClass("otaready-ready");
        this.$.statusText.removeClass("otaready-attention");
        this.$.statusText.setContent(text);
    },

    onTriggerFail: function() {
        this.waits = 45;
        this.$.adviceText.setContent(
            "Couldn't reach the OTA Ready helper service. Restart the TouchPad once and try again.");
        this.$.adviceGroup.show();
    },

    onError: function() {
        this.$.spinner.hide();
        this.$.statusText.setContent(
            "No status yet. The helper may still be starting; wait a few seconds and tap Check Again.");
        this.$.adviceGroup.hide();
        this.$.detailGroup.hide();
    },

    render: function(s) {
        this.$.spinner.hide();
        var v = this.viewFor(s);
        this.$.statusText.setContent(v.headline);
        this.$.statusText.addClass(v.good ? "otaready-ready" : "otaready-attention");
        this.$.statusText.removeClass(v.good ? "otaready-attention" : "otaready-ready");
        this.$.adviceText.setContent(v.advice);
        this.$.adviceGroup.setShowing(!!v.advice);
        this.$.openBtn.setShowing(v.open);
        // No daemon runs on a device that cannot be updated: nothing to check.
        this.$.checkBtn.setShowing(s.offer != "NotEligible");
        this.$.checkedRow.setShowing(s.offer != "NotEligible");
        this.adviceUrl = v.url || null;
        this.$.valVersion.setContent(this.esc(s.version || "?"));
        this.$.valBuild.setContent(this.esc(s.build || "?"));
        this.$.valNduid.setContent(this.esc(s.nduid || "?"));
        this.$.valChecked.setContent(s.time ? this.esc(new Date(s.time * 1000).toLocaleString()) : "never");
        this.$.detailGroup.show();
    },

    viewFor: function(s) {
        switch (s.offer) {
            case "Available":
                return { headline: "An update is available", good: true, open: true,
                         advice: "Open <b>System Updates</b> to download and install it. Keep the " +
                                 "TouchPad charged (at least half) and on Wi-Fi; it restarts twice." };
            case "UpToDate":
                return { headline: "Your TouchPad is up to date", good: true, open: false,
                         advice: s.reason ? "Not offered: " + this.esc(s.reason) : "" };
            case "NetworkFailed":
                return { headline: "Couldn't reach the update server", good: false, open: false,
                         advice: "Check the Wi-Fi connection and tap <b>Check Again</b>." };
            case "InstallSuccessful":
                return { headline: "Update installed", good: true, open: true,
                         advice: this.esc(s.reason) + " was installed. Open <b>System Updates</b> and tap Done." };
            case "InstallFailed":
                return { headline: "The update did not install", good: false, open: true,
                         advice: "Your TouchPad was returned to the version it had. Please use " +
                                 "<b>Send Device Details</b> from the App Menu so we can find out why." };
            case "NotEligible":     // webOS 3.0.5 or older (written by the postinst)
                return { headline: "Not eligible", good: false, open: false, url: this.docsUrl,
                         advice: "Your device needs to be reset with 3.1.0 or later. Please visit " +
                                 "<u>" + this.docsUrl + "</u> to learn how to update your device to " +
                                 "webOS CE 3.1.0 manually." };
            default:
                return { headline: "Status unavailable", good: false, open: false, advice: this.esc(s.reason) };
        }
    },

    adviceTap: function() {
        if (this.adviceUrl) {
            this.$.appManager.call({ target: this.adviceUrl });
        }
    },

    openUpdates: function() {
        this.$.launcher.call({ id: "com.palm.app.updates", params: {} });
    },

    fetchText: function(url, cb) {
        var req = new XMLHttpRequest();
        req.onreadystatechange = function() {
            if (req.readyState != 4) { return; }
            cb(req.responseText || "");
        };
        try {
            req.open("GET", url + "?t=" + (new Date()).getTime(), true);
            req.send(null);
        } catch (e) { cb(""); }
    },

    fetchJson: function(url, cb) {
        this.fetchText(url, function(t) {
            var v = null;
            try { v = JSON.parse(t); } catch (e) {}
            cb(v);
        });
    },

    // --- App menu ----------------------------------------------------------
    doSaveDetails: function() {
        this.$.saveSvc.call({});
    },

    onSaveOk: function(inSender, inResponse) {
        if (inResponse && inResponse.returnValue && inResponse.filename) {
            this.banner("Details saved: " + inResponse.filename);
        } else {
            this.banner("Couldn't save device details. Try again in a moment.");
        }
    },

    onSaveFail: function() {
        this.banner("Couldn't reach the OTA Ready helper. Restart the TouchPad once.");
    },

    banner: function(msg) {
        try {
            if (enyo.windows && enyo.windows.addBannerMessage) {
                enyo.windows.addBannerMessage(msg, "{}");
                return;
            }
        } catch (e) {}
        this.$.adviceText.setContent(this.esc(msg));
        this.$.adviceGroup.show();
    },

    doSendDetails: function() {
        var self = this;
        this.fetchText(this.diagUrl, function(body) {
            if (!body || body.length < 10) {
                body = "OTA Ready device details\n\n" + JSON.stringify(self.lastStatus || {}) + "\n";
            }
            self.$.appManager.call({
                id: "com.palm.app.email",
                params: {
                    summary: "OTA Ready device details",
                    text: body,
                    recipients: [{
                        type: "email", role: 1,
                        value: self.curatorEmail, contactDisplay: "webOS Archive Curator"
                    }]
                }
            });
        });
    },

    esc: function(v) {
        if (v === undefined || v === null) { return ""; }
        return String(v).replace(/&/g, "&amp;").replace(/</g, "&lt;").replace(/>/g, "&gt;");
    }
});
