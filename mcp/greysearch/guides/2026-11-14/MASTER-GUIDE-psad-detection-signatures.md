# Master Guide: psad detection signatures

> **Executive Brief:** In addition, psad incorporates many of the TCP, UDP, and ICMP signatures included in the Snort intrusion detection system. to detect highly suspect scans for various backdoor programs (e.g. *(per github.com)* EvilFTP, GirlFriend, SubSeven), DDoS tools (Mstream, Shaft), and advanced port scans (SYN, FIN, XMAS) which are easily leveraged against a machine via nmap. psad can also alert on Snort signatures that are logged via fwsnort, which makes use of the iptables string match extension to detect traffic that matches application layer signatures. *(per github.com)* Additionally, extensive coverage of psad is included in the book "Linux Firewalls: Attack Detection and Response" published by No Starch Press, and a supporting script in this book is compatible with psad. *(per github.com)*

Assembled live from 3 accepted source(s) and a headless browser, filtered by the two-stage relevance gate. Search lanes this run: local: degraded (2 required engines down: duckduckgo,mojeek); searx.space: tried 11 instance-probes, failed (JSONDecodeError: Expecting value: line 1 column 1 (char 0)); direct keyless: not engaged (enough results); instance preflight: alive 11 of 12 tried. Every section carries its source;

---

## 1. Deep-Dive Overview & Context
In addition, psad incorporates many of the TCP, UDP, and ICMP signatures included in the Snort intrusion detection system. to detect highly suspect scans for various backdoor programs (e.g. (github.com)

EvilFTP, GirlFriend, SubSeven), DDoS tools (Mstream, Shaft), and advanced port scans (SYN, FIN, XMAS) which are easily leveraged against a machine via nmap. psad can also alert on Snort signatures that are logged via fwsnort, which makes use of the iptables string match extension to detect traffic that matches application layer signatures. (github.com) Additionally, extensive coverage of psad is included in the book "Linux Firewalls: Attack Detection and Response" published by No Starch Press, and a supporting script in this book is compatible with psad. (github.com) The latest release can be found at https://github.com/mrash/psad/releases psad makes use of many of the TCP, UDP, and ICMP signatures available in Snort (written by Marty Roesch, see http://www.snort.org). (github.com) About psad: Intrusion Detection and Log Analysis with iptables 5 (5) C Do not share my personal information (github.com)

Search coverage for this run, decomposition: 1 results; instance-preflight: 11 results; general: 8 results. Lanes engaged this run: local: degraded (2 required engines down: duckduckgo,mojeek); searx.space: tried 11 instance-probes, failed (JSONDecodeError: Expecting value: line 1 column 1 (char 0)); direct keyless: not engaged (enough results); instance preflight: alive 11 of 12 tried.

## 2. Full Technical & Feature Breakdown
### GitHub - mrash/psad: psad: Intrusion Detection and Log Analysis with iptables · GitHub


add IP_INFO data to email alerts, defaults to Talos
8720f6a

History
2,385 Commits
Folders and files
Name Last commit message Last commit date

deps

add reputation feed https://rules.emergingthreats.net/blockrules/comp…

doc

moved to doc directory

images

start on markdown format for README

init-scripts

update systemd init script from github user @rathann

misc

use new->

packaging

bump version to 2.4.6

patches

updated iptables trailing space link

selinux

(Miroslav Grepl) Contributed policy file to make psad compatible with…

test

add reputation_scan

CREDITS

minor spacing fixes

ChangeLog

more reputation feed work to enable it within scan data structures

LICENSE

minor spacing fixes

Makefile

minor spacing fixes

README

add README link

README.md

minor spacing fixes

VERSION

start on test suite support for reputation feed tests

auto_dl

minor spacing fixes

fwcheck_psad.pl

implement IP network reputation feed detection (in addition to just s…

icmp6_types

minor spacing fixes

icmp_types

minor spacing fixes

install.answers.example

Added install.answers.example file to illustrate install.pl answers t…

install.pl

add IP_INFO data to email alerts, defaults to Talos

ip_options

kmsgsd.c

minor spacing fixes

nf2csv

minor spacing fixes

pf.os

minor spacing fixes

posf

Removed "$Id$" tags (meaningless for git)

protocols

added 'protocols' file in support of IP protocol scan detection (nmap…

psad

psad.conf

fix for missing semicolon for IP_INFO variable, fixes #59

psad.h

psad_funcs.c

psadwatchd.c

Bugfix: String pointer not dereferenced.

signatures

interim work to replace all 'arachnids' references with valid updated…

snort_rule_dl

strlcat.c

minor spacing fixes

strlcpy.c

minor spacing fixes

psad - Intrusion Detection with iptables Logs
Introduction

The Port Scan Attack Detector psad is a lightweight system daemon written in is designed to work with Linux iptables/ip6tables/firewalld firewalling code to detect suspicious traffic such as port scans and sweeps, backdoors, botnet command and control communications, and more. It features a set of highly configurable danger thresholds (with sensible defaults provided), verbose alert messages that include the source, destination, scanned port range, begin and end times, TCP flags and corresponding nmap options, reverse DNS info, email and syslog alerting, automatic blocking of offending IP addresses via dynamic configuration of iptables rulesets, passive operating system fingerprinting, and DShield reporting. In addition, psad incorporates many of the TCP, UDP, and ICMP signatures included in the Snort intrusion detection system. to detect highly suspect scans for various backdoor programs (e.g. EvilFTP, GirlFriend, SubSeven), DDoS tools (Mstream, Shaft), and advanced port scans (SYN, FIN, XMAS) which are easily leveraged against a machine via nmap. psad can also alert on Snort signatures that are logged via fwsnort, which makes use of the iptables string match extension to detect traffic that matches application layer signatures. As of the 2.4.4 release, psad can also detect the IoT default credentials scanning phase of the Mirai botnet.

The complete feature list is below.

Features
Detection for TCP SYN, FIN, NULL, and XMAS scans as well as UDP scans.
Support for both IPv4 and IPv6 logs generated by iptables and ip6tables respectively.
Detection of many signature rules from the Snort intrusion detection system.
Forensics mode iptables/ip6tables logfile analysis (useful as a forensics tool for extracting scan information from old iptables/ip6tables logfiles).
Passive operating system fingerprinting via TCP syn packets. Two different fingerprinting strategies are supported; a re-implementation of p0f that strictly uses iptables/ip6tables log messages (requires the --log-tcp-options command line switch), and a TOS-based strategy.
Email alerts that contain TCP/UDP/ICMP scan characteristics, reverse dns and whois information, snort rule matches, remote OS guess information, and more.
When combined with fwsnort and the iptables string match extension, psad can generate alerts for application layer buffer overflow attacks, suspicious application commands, and other suspect layer 7 traffic.
Icmp type and code header field validation.
Configurable scan thresholds and danger level assignments.
Iptables ruleset parsing to verify "default drop" policy stance.
IP/network danger level auto-assignment (can be used to ignore or automatically escalate danger levels for certain networks).
DShield alerts.
Auto-blocking of scanning IP addresses via iptables/ip6tables and/or tcpwrappers based on scan danger level. (This feature is NOT enabled by default.)
Parsing of iptables/ip6tables log messages and generation of CSV output that can be used as input to AfterGlow. This allows iptables/ip6tables logs to be visualized. Gnuplot is also supported.
Status mode that displays a summary of current scan information with associated packet counts, iptables/ip6tables chains, and danger levels.
Visualizing Malicious Traffic

psad offers integration with gnuplot and afterglow to produce graphs of malicious traffic. The following two graphs are of the Nachi worm from the Honeynet Scan30 challenge. First, a link graph produced by afterglow after analysis of the iptables log data by psad:

"Nachi Worm Link Graph"

The second shows Nachi worm traffic on an hourly basis from the Scan30 iptables data:

"Nachi Worm Hourly Graph"

Configuration Information

Information on config keywords referenced by psad may be found both in the psad(8) man page, and also here:

http://www.cipherdyne.org/psad/docs/config.html

Methodology

All information psad analyzes is gathered from iptables log messages. psad by default reads the /var/log/messages file for new iptables messages and optionally writes them out to a dedicated file (/var/log/psad/fwdata). psad is then responsible for applying the danger threshold and signature logic in order to determine whether or not a port scan has taken place, send appropriate alert emails, and (optionally) block offending ip addresses. psad includes a signal handler such that if a USR1 signal is received, psad will dump the contents of the current scan hash data structure to /var/log/psad/scan_hash.$$ where "$$" represents the pid of the running psad daemon.

NOTE: Since psad relies on iptables to generate appropriate log messages for unauthorized packets, psad is only as good as the logging rules included in the iptables ruleset. Hence if your firewall is not configured to log packets, then psad will NOT detect port scans or anything else. Usually the best way setup the firewall is with default "drop and log" rules at the end of the ruleset, and include rules above this last rule that only allow traffic that should be allowed through. Upon execution, the psad daemon will attempt to ascertain whether or not such a default deny rule exists, and will warn the user if not. See the FW_EXAMPLE_RULES file for example firewall rulesets that are compatible with psad.

Additionally, extensive coverage of psad is included in the book "Linux Firewalls: Attack Detection and Response" published by No Starch Press, and a supporting script in this book is compatible with psad. This script can be found here:

http://www.cipherdyne.org/LinuxFirewalls/ch01/

Installation

Depending on the Linux distribution, psad may already be available in the default package repository. For example, on Debian or Ubuntu systems, installation is done with a simple:

apt-get install psad

If psad is not available in the package repository, it can be installed with the install.pl script bundled in the psad sources. The install.pl script also handles upgrades if psad is already installed. psad requires several perl modules that may or may not already be installed on your Linux system. These modules are included in the deps/ directory in the psad sources, and are automatically installed by the install.pl script. The list of modules is:

Bit::Vector
Date::Calc
IPTables::ChainMgr
IPTables::Parse
NetAddr::IP
Storable
Unix::Syslog

psad also includes a whois client written by Marco d'Itri (see the deps/whois directory). This client does better than others at collecting the correct whois information for a given IP address.

Firewall Setup

The main requirement for an iptables configuration to be compatible with psad is simply that iptables logs packets. This is commonly accomplished by adding rules to the INPUT and FORWARD chains like so:

iptables -A INPUT -j LOG
iptables -A FORWARD -j LOG

The rules above should be added at the end of the INPUT and FORWARD chains after all ACCEPT rules for legitimate traffic and just before a corresponding DROP rule for traffic that is not to be allowed through the policy. Note that iptables policies can be quite complex with protocol, network, port, and interface restrictions, user defined chains, connection tracking rules, and much more. There are many pieces of software such as Shorewall and Firewall Builder, that build iptables policies and take advantage of the advanced filtering and logging capabilities offered by iptables. Generally the policies built by such pieces of software are compatible with psad since they specifically add rules that instruct iptables to log packets that are not part of legitimate traffic. Psad can be configured to only analyze those iptables messages that contain specific log prefixes (which are added via the --log-prefix option), but the default is for psad to analyze all iptables log messages for evidence of port scans, probes for backdoor programs, and other suspect traffic.

Platforms

psad generally runs on Linux systems, and is available in the package repositories of many major Linux distributions. If there are any operational issues with psad, please open an issue on github

License

psad is released as open source software under the terms of the GNU General Public License (GPL v2+). The latest release can be found at https://github.com/mrash/psad/releases

psad makes use of many of the TCP, UDP, and ICMP signatures available in Snort (written by Marty Roesch, see http://www.snort.org). Snort is a registered trademark of Sourcefire, Inc.

Contact

All feature requests and bug fixes are managed through github issues tracking. However, you can email me (michael.rash_AT_gmail.com), or reach me through Twitter (@michaelrash).

About

psad: Intrusion Detection and Log Analysis with iptables

5
 (5)
C

Do not share my personal information



![GitHub - mrash/psad: psad: Intrusion Detection and Log Analy](https://github.githubassets.com/assets/platform-4ce65ae0bf273ce2.png)


![GitHub - mrash/psad: psad: Intrusion Detection and Log Analy](https://github.githubassets.com/assets/platform-dark-ac89fbf373737ed3.png)


![GitHub - mrash/psad: psad: Intrusion Detection and Log Analy](https://github.githubassets.com/assets/copilot-e2b89335a66dba00.png)


![GitHub - mrash/psad: psad: Intrusion Detection and Log Analy](https://github.githubassets.com/assets/copilot-dark-2b28403b6080e898.png)


![GitHub - mrash/psad: psad: Intrusion Detection and Log Analy](https://github.githubassets.com/assets/changelog-fd687bff072883b0.png)


![GitHub - mrash/psad: psad: Intrusion Detection and Log Analy](https://github.githubassets.com/assets/changelog-dark-b1c25ae971bd641b.png)


![GitHub - mrash/psad: psad: Intrusion Detection and Log Analy](https://github.githubassets.com/assets/universe-a98cd54821b27569.png)


![GitHub - mrash/psad: psad: Intrusion Detection and Log Analy](https://github.githubassets.com/assets/universe-a98cd54821b27569.png)


![nachi-worm-link-graph](https://github.com/mrash/psad/raw/master/images/nachi_worm.gif)


![nachi-worm-link-graph](https://github.com/mrash/psad/raw/master/images/nachi_worm.gif)


![nachi-worm-hourly-graph](https://github.com/mrash/psad/raw/master/images/nachi_worm_hourly.png)


| Name | Name | Last commit message | Last commit date |
| --- | --- | --- | --- |
| deps | deps | add reputation feed https://rules.emergingthreats.net/blockrules/comp… |  |
| doc | doc | moved to doc directory |  |
| images | images | start on markdown format for README |  |
| init-scripts | init-scripts | update systemd init script from github user @rathann |  |
| misc | misc | use new-> |  |
| packaging | packaging | bump version to 2.4.6 |  |
| patches | patches | updated iptables trailing space link |  |
| selinux | selinux | (Miroslav Grepl) Contributed policy file to make psad compatible with… |  |
| test | test | add reputation_scan |  |
| CREDITS | CREDITS | minor spacing fixes |  |
| ChangeLog | ChangeLog | more reputation feed work to enable it within scan data structures |  |
| LICENSE | LICENSE | minor spacing fixes |  |
| Makefile | Makefile | minor spacing fixes |  |
| README | README | add README link |  |
| README.md | README.md | minor spacing fixes |  |
| VERSION | VERSION | start on test suite support for reputation feed tests |  |
| auto_dl | auto_dl | minor spacing fixes |  |
| fwcheck_psad.pl | fwcheck_psad.pl | implement IP network reputation feed detection (in addition to just s… |  |
| icmp6_types | icmp6_types | minor spacing fixes |  |
| icmp_types | icmp_types | minor spacing fixes |  |
| install.answers.example | install.answers.example | Added install.answers.example file to illustrate install.pl answers t… |  |
| install.pl | install.pl | add IP_INFO data to email alerts, defaults to Talos |  |
| ip_options | ip_options | start on test suite support for reputation feed tests |  |
| kmsgsd.c | kmsgsd.c | minor spacing fixes |  |
| nf2csv | nf2csv | minor spacing fixes |  |
| pf.os | pf.os | minor spacing fixes |  |
| posf | posf | Removed "$Id$" tags (meaningless for git) |  |
| protocols | protocols | added 'protocols' file in support of IP protocol scan detection (nmap… |  |
| psad | psad | add IP_INFO data to email alerts, defaults to Talos |  |
| psad.conf | psad.conf | fix for missing semicolon for IP_INFO variable, fixes #59 |  |
| psad.h | psad.h | start on test suite support for reputation feed tests |  |
| psad_funcs.c | psad_funcs.c | start on test suite support for reputation feed tests |  |
| psadwatchd.c | psadwatchd.c | Bugfix: String pointer not dereferenced. |  |
| signatures | signatures | interim work to replace all 'arachnids' references with valid updated… |  |
| snort_rule_dl | snort_rule_dl | Removed "$Id$" tags (meaningless for git) |  |
| strlcat.c | strlcat.c | minor spacing fixes |  |
| strlcpy.c | strlcpy.c | minor spacing fixes |  |
| View all files |  |  |  |



```
iptables -A INPUT -j LOG
iptables -A FORWARD -j LOG
```


- [Skip to content](https://github.com/mrash/psad#start-of-content)
- [https://github.com/](https://github.com/)
- [Sign in](https://github.com/login?return_to=https%3A%2F%2Fgithub.com%2Fmrash%2Fpsad)
- [GitHubRepository hosting, code review, and collaboration](https://github.com/platform)
- [CopilotAI coding agent for tasks, projects, and automated work](https://github.com/features/copilot)
- [ActionsCI/CD and automation](https://github.com/features/actions)
- [Code QualityQuality analysis, fixes, and enforcement](https://github.com/features/code-quality)
- [CodespacesCloud development environments](https://github.com/features/codespaces)
- [Code SecurityVulnerability detection and remediation](https://github.com/security/advanced-security/code-security)
- [Secret ProtectionSecret scanning and leak prevention](https://github.com/security/advanced-security/secret-protection)
- [All Features](https://github.com/features)
- [Documentation](https://docs.github.com/en)
- [Training](https://learn.github.com/skills)
- [Certifications](https://learn.github.com/credentials)
- [Build with Copilot](https://github.com/features/ai)
- [Customize Copilot](https://docs.github.com/en/copilot/how-tos/copilot-on-github/customize-copilot/customize-copilot-overview)
- [Integrations](https://github.com/marketplace)
- [Trending repos](https://github.com/trending)
- [GitHub Sponsors](https://github.com/open-source/sponsors)
- [Developer articles](https://github.com/resources/articles)
- [ChangelogYour source for the latest features, improvements, and fixes across GitHub products, all in one place.](https://github.blog/changelog/)
- [Enterprises](https://github.com/enterprise)
- [Team](https://github.com/team)
- [Startups](https://github.com/enterprise/startups)
- [Nonprofits](https://github.com/solutions/industry/nonprofits)
- [Healthcare](https://github.com/solutions/industry/healthcare)
- [Financial services](https://github.com/solutions/industry/financial-services)
- [Manufacturing](https://github.com/solutions/industry/manufacturing)
- [Government](https://github.com/solutions/industry/government)
- [See all industries](https://github.com/solutions/industry)
- [Why GitHub](https://github.com/why-github)
- [Customer Stories](https://github.com/customer-stories)
- [Business insights](https://github.com/solutions/executive-insights)
- [Trust Center](https://github.com/trust-center)
- [GitHub Advanced SecurityEnterprise-grade code security](https://github.com/security/advanced-security)
- [Copilot for businessEnterprise-grade AI features](https://github.com/features/copilot/copilot-business)
- [Premium SupportEnterprise-grade 24/7 support](https://github.com/enterprise/premium-support)
- [Documentation](https://docs.github.com/en)
- [Resource center](https://github.com/resources)
- [Blog](https://github.blog/)
- [Events & webinars](https://github.com/resources/events)
- [Community Forum](https://github.com/orgs/community/discussions)
- [Customer Stories](https://github.com/customer-stories)
- [Integrations](https://github.com/marketplace)
- [Customer support](https://help.github.com/)
- [Training](https://learn.github.com/skills)
- [GitHub Status](https://www.githubstatus.com/)
- [About](https://github.com/about)
- [Partners](https://github.com/partners)
- [Changelog](https://github.blog/changelog/)
- [GitHub UniverseThe event for developers, by developers — talks, workshops, and what’s next for GitHub.](https://githubuniverse.com/)
- [Pricing](https://github.com/pricing)
- [Sign in](https://github.com/login?return_to=https%3A%2F%2Fgithub.com%2Fmrash%2Fpsad)
- [Sign up](https://github.com/signup?ref_cta=Sign+up&ref_loc=header+logged+out&ref_page=%2F%3Cuser-name%3E%2F%3Crepo-name%3E&source=header-repo&source_repo=mrash%2Fpsad)
- [Reload](https://github.com/mrash/psad)
- [Reload](https://github.com/mrash/psad)
- [Reload](https://github.com/mrash/psad)
- [mrash](https://github.com/mrash)
- [psad](https://github.com/mrash/psad)
- [Code](https://github.com/mrash/psad)
- [Issues
27
 (27)](https://github.com/mrash/psad/issues)
- [Pull requests
2
 (2)](https://github.com/mrash/psad/pulls)
- [Projects](https://github.com/mrash/psad/projects)
- [Wiki](https://github.com/mrash/psad/wiki)
- [Security and quality](https://github.com/mrash/psad/security)
- [Insights](https://github.com/mrash/psad/pulse)
- [https://github.com/mrash/psad](https://github.com/mrash/psad)
- [psad](https://github.com/mrash/psad)
- [Notifications](https://github.com/login?return_to=%2Fmrash%2Fpsad)
- [Fork78
 (78)](https://github.com/login?return_to=%2Fmrash%2Fpsad)
- [Star440
 (440)](https://github.com/login?return_to=%2Fmrash%2Fpsad)
- [www.cipherdyne.org/psad/](http://www.cipherdyne.org/psad/)
- [firewall](https://github.com/topics/firewall)
- [intrusion-detection](https://github.com/topics/intrusion-detection)
- [iptables](https://github.com/topics/iptables)
- [iptables-logs](https://github.com/topics/iptables-logs)
- [log-analysis](https://github.com/topics/log-analysis)
- [mirai-bot](https://github.com/topics/mirai-bot)
- [snort](https://github.com/topics/snort)
- [Readme](https://github.com/mrash/psad#readme-ov-file)



### psad - Intrusion Detection with iptables, iptables Log Analysis, iptables Policy Analysis


psad: Intrusion Detection and Log Analysis with iptables
psad is a collection of three lightweight system daemons (two main daemons and one helper daemon) that run on Linux machines and analyze iptables log messages to detect port scans and other suspicious traffic. A typical deployment is to run psad on the iptables firewall where it has the fastest access to log data.

psad incorporates many signatures from the Snort intrusion detection system to detect probes for various backdoor programs (e.g. EvilFTP, GirlFriend, SubSeven), DDoS tools (mstream, shaft), and advanced port scans (FIN, NULL, XMAS) which are easily leveraged against a machine via nmap. When combined with fwsnort and the Netfilter string match extension, psad is capable of detecting many attacks described in the Snort rule set that involve application layer data. In addition, psad makes use of various packet header fields associated with TCP SYN packets to passively fingerprint remote operating systems (in a manner similar to p0f) from which scans originate. Further, psad can be integrated with Logstash, and also offers support for UFW firewalls [1]. For more information, see the complete list of features offered by psad.

Significant coverage of psad, including a full discussion of its iptables log analysis capabilities and the ability to interface with graphing software such as AfterGlow and Gnuplot, can be found in the book Linux Firewalls: Attack Detection and Response with iptables, psad, and fwsnort. Several iptables log visualizations from Chapter 14 of the book are available online, and two such examples appear below. The first example is a link graph produced by AfterGlow of iptables log messages that are indicative of the Nachi Worm:
For the second example, psad interfaces with Gnuplot to produce a graph of the number of TCP SYN packets to destination ports per hour. Clearly discernible is a spike on March 27th, and further analysis of the iptables log data indicates a heavy port scan is the cause:
The data source for the two visualizations above is the iptables log data from the Scan30 Honeynet Challenge. The complete psad Honeynet challenge analysis pages can be found here: psad Honeynet challenge graphs

psad is developed around three main principles:

Good network security starts with a properly configured firewall.
A significant amount of intrusion detection data can be gleaned from firewalls logs, especially if the logs provide information on nearly every field of the network and transport headers (and even application layer signature matches as in Netfilter's case when also running fwsnort).
Suspicious traffic should not be detected at the expense of trying to also block such traffic.

History
psad began as part of the Bastille Linux project in the fall of 1999 after it was decided Bastille needed to have a lightweight network intrusion detection component, and the result was the "Bastille-NIDS". In March, 2001 Bastille-NIDS was made into its own project and called the "Port Scan Attack Detector" (psad). The development cycle for psad it quite active and a major release is made on average once every few months.[1] Logstash and UFW integration are possible thanks to Rinck Sonnenberg.
» download
» documentation
fwsnort
gpgdir
IPTables::Parse
IPTables::ChainMgr

Linux Firewalls Book
Tweets by michaelrash

Recent Blog Posts
Software Release: fwknop-2.6.11
Wireguard, macOS, and Linux Virtual Machines
Software Release: fwknop-2.6.10
Software Release: psad-2.4.6 and fwsnort-1.6.8
Software Release: fwknop-2.6.9
Single Packet Authorization and Third Party Devices
Software Release: fwknop-2.6.7
Android Fwknop2 Client and OpenWRT
Archives...
Categories
Port Knocking and SPA (49)
IDS and iptables (25)
In The News (27)
Trac (4)
More...

Design by Andreas Viklund.



![AfterGlow graph of the Nachi Worm derived from psad parsing of iptables LOG messages](https://www.cipherdyne.org/images/honeynet/scan34/nachi_worm.gif)


![psad Gnuplot of TCP SYN packets per hour](https://www.cipherdyne.org/LinuxFirewalls/ch14/fig14-2.png)


![Linux Firewalls: Attack Detection and Response with iptables, psad, and fwsnort](https://www.cipherdyne.org/images/LF_cover.jpg)


|  |
| --- |



- [cipherdyne.org](http://www.cipherdyne.org/)
- [Home](https://www.cipherdyne.org/)
- [Blog](https://www.cipherdyne.org/blog/)
- [Software](https://www.cipherdyne.org/about.html)
- [Author](https://www.cipherdyne.org/author.html)
- [Contact](https://www.cipherdyne.org/contact.html)
- [iptables](http://www.netfilter.org/)
- [Download](https://www.cipherdyne.org/psad/download/)
- [Documentation](https://www.cipherdyne.org/psad/docs/)
- [Features](https://www.cipherdyne.org/psad/docs/features.html)
- [Source Code](https://github.com/mrash/psad)
- [Mailing List](http://lists.sourceforge.net/lists/listinfo/psad-discuss)
- [Snort](http://www.snort.org/)
- [fwsnort](https://www.cipherdyne.org/fwsnort/)
- [p0f](http://lcamtuf.coredump.cx/p0f.shtml)
- [integrated with Logstash](https://gist.github.com/netson/cc6ffa751aa4610c13c0)
- [UFW firewalls](https://gist.github.com/netson/c45b2dc4e835761fbccc)
- [[1]](https://www.cipherdyne.org/psad/#thanks)
- [features](https://www.cipherdyne.org/psad/docs/features.html)
- [AfterGlow](http://afterglow.sourceforge.net/)
- [Gnuplot](http://www.gnuplot.info/)
- [Linux Firewalls: Attack Detection and Response with iptables, psad, and fwsnort](https://www.cipherdyne.org/LinuxFirewalls)
- [available online](https://www.cipherdyne.org/LinuxFirewalls/ch14/iptables_log_visualizations.html)
- [Nachi Worm](http://en.wikipedia.org/wiki/Nachi_worm)
- [https://www.cipherdyne.org/images/honeynet/scan34/nachi_worm.gif](https://www.cipherdyne.org/images/honeynet/scan34/nachi_worm.gif)
- [https://www.cipherdyne.org/LinuxFirewalls/ch14/fig14-2.png](https://www.cipherdyne.org/LinuxFirewalls/ch14/fig14-2.png)
- [Scan30 Honeynet Challenge](http://www.honeynet.org/scans/scan30/)
- [psad Honeynet challenge graphs](https://www.cipherdyne.org/psad/honeynet/)
- [fwsnort](https://www.cipherdyne.org/fwsnort%22)
- [Bastille Linux](http://www.bastille-linux.org/)
- [fwknop](https://www.cipherdyne.org/fwknop/)
- [afl-cov](https://www.cipherdyne.org/afl-cov/)
- [psad](https://www.cipherdyne.org/psad/)
- [» download](https://www.cipherdyne.org/psad/download/)
- [» documentation](https://www.cipherdyne.org/psad/docs/)
- [fwsnort](https://www.cipherdyne.org/fwsnort/)
- [gpgdir](https://www.cipherdyne.org/gpgdir/)
- [IPTables::Parse](https://www.cipherdyne.org/modules/IPTables-Parse.html)
- [IPTables::ChainMgr](https://www.cipherdyne.org/modules/IPTables-ChainMgr.html)
- [https://twitter.com/michaelrash](https://twitter.com/michaelrash)
- [https://www.google.com/+MichaelRash](https://www.google.com/+MichaelRash)
- [https://www.cipherdyne.org/atom.xml](https://www.cipherdyne.org/atom.xml)
- [https://www.linkedin.com/pub/michael-rash/0/81/209](https://www.linkedin.com/pub/michael-rash/0/81/209)
- [https://www.cipherdyne.org/LinuxFirewalls](https://www.cipherdyne.org/LinuxFirewalls)
- [Tweets by michaelrash](https://twitter.com/michaelrash?ref_src=twsrc%5Etfw)
- [Software Release: fwknop-2.6.11](https://www.cipherdyne.org/blog/2024/02/software-release-fwknop-2.6.11.html)
- [Wireguard, macOS, and Linux Virtual Machines](https://www.cipherdyne.org/blog/2018/10/wireguard-macos-and-linux-virtual-machines.html)
- [Software Release: fwknop-2.6.10](https://www.cipherdyne.org/blog/2018/08/software-release-fwknop-2.6.10.html)
- [Software Release: psad-2.4.6 and fwsnort-1.6.8](https://www.cipherdyne.org/blog/2018/07/software-release-psad-2.4.6-and-fwsnort-1.6.8.html)
- [Software Release: fwknop-2.6.9](https://www.cipherdyne.org/blog/2016/06/software-release-fwknop-2.6.9.html)
- [Single Packet Authorization and Third Party Devices](https://www.cipherdyne.org/blog/2015/12/single-packet-authorization-and-third-party-devices.html)
- [Software Release: fwknop-2.6.7](https://www.cipherdyne.org/blog/2015/08/software-release-fwknop-2.6.7.html)
- [Android Fwknop2 Client and OpenWRT](https://www.cipherdyne.org/blog/2015/06/android-fwknop2-client-and-openwrt.html)
- [Archives...](https://www.cipherdyne.org/blog/archives.html)
- [Port Knocking and SPA (49)](https://www.cipherdyne.org/blog/categories/port-knocking-and-spa.html)
- [IDS and iptables (25)](https://www.cipherdyne.org/blog/categories/intrusion-detection-and-iptables.html)
- [Network Security (3)](https://www.cipherdyne.org/blog/categories/network-security.html)
- [Publications (20)](https://www.cipherdyne.org/blog/categories/publications.html)
- [Programming (10)](https://www.cipherdyne.org/blog/categories/programming.html)
- [DNS (3)](https://www.cipherdyne.org/blog/categories/dns.html)
- [git (3)](https://www.cipherdyne.org/blog/categories/git.html)
- [System Administration (4)](https://www.cipherdyne.org/blog/categories/system-administration.html)
- [Conference Talks (22)](https://www.cipherdyne.org/blog/categories/conference-talks.html)
- [Software Releases (130)](https://www.cipherdyne.org/blog/categories/software-releases.html)
- [In The News (27)](https://www.cipherdyne.org/blog/categories/in-the-news.html)
- [Trac (4)](https://www.cipherdyne.org/blog/categories/trac.html)
- [More...](https://www.cipherdyne.org/blog/archives.html)
- [Terms of Use](https://www.cipherdyne.org/Cipherdyne_Terms_of_Use.doc)
- [Michael Rash](https://www.cipherdyne.org/author.html)
- [Andreas Viklund](http://andreasviklund.com/)



### How To Use psad to Detect Network Intrusion Attempts on an Ubuntu VPS | DigitalOcean


Prompt Caching is now GA on DigitalOcean Serverless Inference

Introducing Agent Droplets

Black Friday on Cloudways: Get 80% off for 2 months, plus unlimited free migrations

Featured AI Products

Compute

Containers and Images

Managed Databases

Management and Dev Tools

Networking

Security

Storage

Browse all products
Featured AI Products

Managed Agents

Run AI agents in the cloud with governed tool access

New

Learning Services

Improve agents and models with evidence

New

Data Services

Store, retrieve, and surface the context you need

Inference Engine

Run inference at scale with policy-driven routing

Model Library

Discover, compare, and evaluate AI models

GPU Droplets

GPU-powered virtual machines to build and run AI apps

Browse all products
Solutions

AI/ML

CMS

Data and IoT

Developer Tools

Gaming and Media

Hosting

Security and Networking

Startups and SMBs

Web and App Platforms

See all solutions
AI/ML

AI HR Knowledge Assistant

Deploy AI tools developed for Human Resources

AI Training GPU

Accelerate model training with dedicated GPU infrastructure

AI Recommendation Engine

Build tools to personalize user experiences

Multimodal AI

Run models that process multiple data types

GPU Clusters

GPUs clustered together for large-scale tasks

GPU Inference

Serve models efficiently with optimized GPU compute

Developers

Community

Documentation

Developer Tools

Get Involved

Utilities and Help

Community

Blog

The latest product releases and insights from our experts

The Wave

Content to level up your business

Tutorials

Our extensive library of technical articles

Q&A

Answers to your cloud and coding questions

YouTube

Educational content and tutorials

Visit DigitalOcean's Community Site
Partners

Become a Partner

Marketplace

Become a Partner

About Partner Pod

Discounts, revenue share, and more for businesses

AI Partner Program

Boost your AI business

DigitalOcean Startups

Resources and support to propel your startup

Partners Directory

Current list of DigitalOcean Partners

Customer Stories

Customers growing on DigitalOcean

Need help? Talk to an expert
Become a Partner
Pricing

How To Use psad to Detect Network Intrusion Attempts on an Ubuntu VPS
TutorialsSecurityHow To Use psad to Detect Network Intrusion Attempts on an Ubuntu VPS
Tutorial
Published on January 10, 2014

By Justin Ellingwood

Install psad
Configure IPTables Rules
Configure psad to Detect Scans

Being able to detect network activity that may indicate an intrusion attempt can help you take appropriate actions before an event occurs. Intrusion detection systems are available for this specific reason.

Intrusion detection systems are used to log suspicious connections and report when it looks like unusual activity is taking place. Some programs are used purely as a notification system, while others can actively attempt to block traffic that appear to be intent on causing harm.

The psad tool, which stands for port scan attack detection, is a piece of software that actively monitors your firewall logs to determine if a scan or attack event is in progress. It can then alert administrators, or take active steps to deter the threat.

In this guide, we will be exploring how to install and configure psad on an Ubuntu 12.04 VPS. The procedures should be fairly similar on other distributions.

Install psad

The psad intrusion detection system is available in Ubuntu’s default repositories, so it can be easily acquired through apt:

sudo apt-get update
sudo apt-get install psad

In order to configure mail delivery to alert the administrator, you will be asked to configure the postfix mail server.

In most cases, you can select “Internet Site”, and then enter the domain name associated with your server. This will be the domain portion of the name used in the “From” field in emails generated by psad.

Configure IPTables Rules

The way that psad detects activity on your server’s ports is by monitoring the logs produced by a firewall application. Ubuntu ships with the iptables firewall by default, but it is completely unconfigured and is not monitoring or blocking anything by default.

Although you could get away with typing the following commands to simply enable logging, we will do a more robust configuration:

sudo iptables -A INPUT -j LOG
sudo iptables -A FORWARD -j LOG

If you entered the rules above, flush the rules before configuring so that we can start from scratch.

sudo iptables -F

You can see the current rules (which should only include the default policies at this point), by typing:

sudo iptables -S

-P INPUT ACCEPT
-P FORWARD ACCEPT
-P OUTPUT ACCEPT

We can now start appending our rules, mainly to the INPUT chain. We want to tell iptables to drop connections that we do not need or want. We need to add the rules to explicitly allow our authorized connections prior to adding restrictions.

The first rule will allow all traffic generated by our server, directed at our server. This type of connection is generally used for services to communicate with each other and pass information easily:

sudo iptables -A INPUT -i lo -j ACCEPT

Next, we want to add a rule to explicitly allow all traffic related to an existing connection. This will allow our current sessions to continue uninterrupted:

sudo iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT

Next, we can add the services that we wish to keep open to the public. For SSH, we can add a line like this:

sudo iptables -A INPUT -p tcp --dport 22 -j ACCEPT

If we have a web server running on the default port 80, we can add a rule like this:

sudo iptables -A INPUT -p tcp --dport 80 -j ACCEPT

Add any other ports for legitimate, publicly accessible services you wish to leave open with the same syntax:

sudo iptables -A INPUT -p protocol --dport port_num -j ACCEPT

After you are done adding the legitimate services, we will drop all remaining connections. Anything that hits this rule did not match our rules that were for legitimate traffic.

Before we do that though, this we need to add the rule that tell iptables to begin logging traffic. This will cause iptables to log traffic that has not been handled yet.

sudo iptables -A INPUT -j LOG

We also should add this rule to the forward chain in case we end up forwarding traffic elsewhere.

sudo iptables -A FORWARD -j LOG

Finally, let’s drop all extraneous traffic that hasn’t matched yet. We can do this by either adding a rule that matches everything in the chain to the end like this:

sudo iptables -A INPUT -j DROP

Or, we can use the built-in policy functionality to configure what happens when a packet passes down the chain without matching any rules:

sudo iptables -P INPUT DROP

The results are functionally exactly the same.

One thing to note is that if you ever need to flush your iptables and you set up a DROP policy (instead of adding it as a rule at the bottom of the chain), you should reverse the policy before flushing:

sudo iptables -P INPUT ACCEPT
sudo iptables -F

If you fail to do this, your iptables rules will be flushed and only the default policy of dropping all incoming packets will remain. This will cut off all network traffic coming into your server, including traffic from your SSH connection.

By default, iptables does not maintain its rules between reboots, so after you have tested your configuration and are sure that it does what you would like, you can download and enable a tool that makes these rules persistent:

sudo apt-get install iptables-persistent
sudo service iptables-persistent start

Configure psad to Detect Scans

Now that we have an iptables rule set configured with what is called a “default drop” policy, we can begin configuring psad to start parsing the logs.

Open the main psad configuration file with root privileges:

sudo nano /etc/psad/psad.conf

The first things you should modify are at the top of the file. You should change the EMAIL_ADDRESSES parameter to match the email addresses you would like to notify when a report is generated. You should also modify the HOSTNAME to match your domain so that it references the correct machine:

EMAIL_ADDRESSES address1@domain.com, address2@other.com;

HOSTNAME your_domain.com;

Be sure to end each of your lines with a semi-colon (;) for psad to read the file correctly.

One section that you probably want to take a look at is the “danger levels” declarations. These levels are a way for psad to categorize threat levels.

They are automatically determined by the number of packets involved in an event, but you can assign certain types of traffic to be a certain danger level also. The default thresholds for each level to be reached are:

DANGER_LEVEL1 5;
DANGER_LEVEL2 15;
DANGER_LEVEL3 150;
DANGER_LEVEL4 1500;
DANGER_LEVEL5 10000;

You can change these levels depending on the level of sensitivity you would like psad to use for alerts.

You can also configure how sensitive psad will be through the PORT_RANGE_SCAN_THRESHOLD parameter. This determines the number of ports in a range that must be scanned before an alert is raised. The default is that an alert is raised after two ports are scanned.

PORT_RANGE_SCAN_THRESHOLD 1;

One of the most important things to configure is the IPT_SYSLOG_FILE parameter, because it currently is not pointed at a file that syslog uses by default.

Modify this to point at the syslog file, where psad will actually have an opportunity to look through active logs:

IPT_SYSLOG_FILE /var/log/syslog;

If you use certain ports for things like port knocking, you should tell psad to ignore attempts on these ports so that you do not trigger alerts through routine activities:

IGNORE_PORTS ports_or_range_to_ignore;

You can similarly ignore messages based on other things through the appropriately named IGNORE_PROTOCOLS, IGNORE_INTERFACES, and IGNORE_LOG_PREFIXES parameters.

If you find that you are getting alerts too often, you can set the threshold on emails by adjusting what level must be reached before an email is sent:

MIN_DANGER_LEVEL 1; # Controls psad logging and email alerts
EMAIL_ALERT_DANGER_LEVEL 1; # Applies only for email alerts

You can also limit the number of emails directly by setting this:

EMAIL_LIMIT 0;

Zero means there is no limit. This limit is the number of emails that can be generated by threats from a single IP address.

For the time being, let’s save and close the file.

Implement psad Intrusion Detection

Now that we have a basic psad configuration in place, complete with alert capabilities, we can implement our policies and activate our system.

Before we begin, we should update psad’s signature definitions so that it can correctly recognize known attack types. Do this by calling:

sudo psad --sig-update

This will fetch the latest files and update the database.

Now, we need to restart the service to use these updates and to implement our configuration changes. Type:

sudo service psad restart

This will implement our log monitoring. To see the current status of psad detected events, type:

sudo service psad status

[+] psadwatchd (pid: 3737) %CPU: 0.0 %MEM: 0.0
Running since: Fri Jan 10 15:36:04 2014

[+] psad (pid: 3735) %CPU: 0.0 %MEM: 0.3
Running since: Fri Jan 10 15:36:04 2014
Command line arguments: [none specified]
Alert email address(es): example@domain.com

[+] Version: psad v2.1.7

[+] Top 50 signature matches:
[NONE]

[+] Top 25 attackers:
[NONE]

[+] Top 20 scanned ports:
[NONE]

[+] iptables log prefix counters:
[NONE]

Total packet counters: tcp: 0, udp: 0, icmp: 0

[+] IP Status Detail:
[NONE]

Total scan sources: 0
Total scan destinations: 0

[+] These results are available in: /var/log/psad/status.out

As you can see, nothing has been found yet. We can also see that detected events are logged to files located at /var/log/psad/.

Perform a Test Port Scan

From another computer, we should try to scan our server’s ports to generate some hits on the firewall. We can do this with the nmap utility.

We will do a SYN tcp port scan from another machine. We will tell it to assume that our host is up by passing it the -PN option:

sudo nmap -PN -sS server_domain_or_ip

Starting Nmap 5.51 ( http://nmap.org ) at 2014-01-10 15:54 EST
Nmap scan report for server_domain_or_ip
Host is up (0.013s latency).
Not shown: 999 filtered ports
PORT STATE SERVICE
22/tcp open ssh

Nmap done: 1 IP address (1 host up) scanned in 6.84 seconds

As you can see, this scan indicates what I configured for my firewall. Every port is labeled as “filtered” indicating that it is protected by a firewall, except for the SSH port, which is exposed.

On your server, you should re-run the status command:

sudo service psad status

You should see a lot larger list of alerts. Because the event was just a 1000 port scan, it triggered a signature match for a lot of different threats. For a more pointed attack, which is focused on a specific port or entry point, the signature would be much more helpful.

If you set up email alerts, you should have also have received an email or two. If you have a domain associated with the computer you scanned from, you should see a “who is” report on the owner associated with the scanning.

You can use this to attempt to contact the owner of the IP or perhaps the ISP or hosting provider.

Implement Intrusion Prevention

Now that we have verified that we can detect activity trying to access our server, we can optionally implement a prevention mechanism where psad can automatically modify iptables rules to ban scanners.

Before we do this, we should take a look at the auto_dl file:

sudo nano /etc/psad/auto_dl

This file specifies what danger level we should automatically set certain IP addresses. For instance, if we have an attacker who continuously tries to probe our system, we can set them to danger level 5 automatically:

attacker_ip 5;

On the other hand, you can basically exempt certain IP addresses from eliciting a reaction from psad. We could add the localhost here and set it to “0” if we hadn’t added a rule in our iptables explicitly.

For our purposes, since we are going to be setting psad to automatically block traffic from a detected threat IP, we should add our home computer to this list so that we do not lock ourselves out:

local_computer_ip 0;

Save and close the file when you are finished.

Open up the psad configuration file again:

sudo nano /etc/psad/psad.conf

Search for the parameter called ENABLE_AUTO_IDS. This is the rule that allows psad to modify our firewall to block certain addresses. If you want to automatically do this, you can change it like this:

ENABLE_AUTO_IDS Y;

Next, we want to decide what constitutes a threat level large enough to block the offending IP. We can do that by adjusting this parameter:

AUTO_IDS_DANGER_LEVEL 5;

Another important option is the total block time in seconds:

AUTO_BLOCK_TIMEOUT 3600;

This will block them for an hour by default.

Test Intrusion Prevention

We can test out how this works by temporarily banning ourselves. In the same configuration file, we are going to set these parameters:

ENABLE_AUTOIDS Y;
AUTO_IDS_DANGER_LEVEL 4;
AUTO_BLOCK_TIMEOUT 60;

This will turn on automatic firewall configuration, will set the threshold to danger level 4, which we hit with a normal SYN scan, and set the block time for 60 seconds.

Save and close the file.

Open the auto_dl file if you added your home IP address, and temporarily comment that out.

# local_computer_ip 0;

Now, restart psad to make it re-read these files:

sudo service psad restart

From your home computer, you can re-run the scan you did last time:

sudo nmap -PN -sS server_domain_or_ip

At this point, after a few seconds, if you are connected to your psad machine through SSH, your connection should be dropped. You will not be able to connect again for 60 seconds.

This is because psad took action when your scan had hit enough ports to hit danger level 4. It modified the iptables rules to divert traffic to other chains that temporarily blocked your IP.

Once you are able to log in again, you can see the remnants of this diversion by checking out your iptable rules:

sudo iptables -S

-P INPUT DROP
-P FORWARD ACCEPT
-P OUTPUT ACCEPT
-N PSAD_BLOCK_FORWARD
-N PSAD_BLOCK_INPUT
-N PSAD_BLOCK_OUTPUT
-A INPUT -j PSAD_BLOCK_INPUT
-A INPUT -i lo -j ACCEPT
-A INPUT -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
-A INPUT -p tcp -m tcp --dport 22 -j ACCEPT
-A INPUT -j LOG
-A FORWARD -j PSAD_BLOCK_FORWARD
-A FORWARD -j LOG
-A OUTPUT -j PSAD_BLOCK_OUTPUT

As you can see, more chains were created and all input was directed into one of these chains. During the ban, this chain would have dropped connection attempts for your home connection’s IP.

Now that you have tested this functionality, revert it back to what you’d like to use. You should probably increase the ban length if you are planning on actually using this functionality. Additionally, you should re-add the IP addresses that you know you will be connecting to:

local_computer_ip 0;

ENABLE_AUTOIDS Y;
AUTO_IDS_DANGER_LEVEL 5;
AUTO_BLOCK_TIMEOUT 3600;

Don’t forget to restart psad when you are done configuring your service for real-world application:

sudo service psad restart

Keep in mind, there are certain types of attacks that can spoof the source IP address. This means that an attacker who suspects that you have auto-blocking functionality enabled could cause you to accidentally ban legitimate sites or services. Be very careful and weigh the costs and benefits of this type of a configuration.

Conclusion

By correctly configuring a network intrusion detection tool like psad, you increase your chances of getting the needed warnings about threats before a problem actually happens. Tools like psad can give you advanced warning and can deal with some situations automatically.

The key to using psad effectively is to configure danger levels and email alerts appropriately, and then follow up on any problems. This tool, coupled with other intrusion detection resources like tripwire can provide fairly good coverage to be able to detect intrusion attempts.

Thanks for learning with the DigitalOcean Community. Check out our offerings for compute, storage, networking, and managed databases.

Learn more about our products

About the author

Former Senior Technical Writer at DigitalOcean, specializing in DevOps topics across multiple Linux distributions, including Ubuntu 18.04, 20.04, 22.04, as well as Debian 10 and 11.

Category:
Tutorial
Tags:
Still looking for an answer?
Ask a question
Search for more help
Was this helpful?

Leave a comment...

This textbox defaults to using Markdown to format your answer.

You can type !ref in this text area to quickly search our full set of tutorials, documentation & marketplace offerings and insert the link!

I did ‘sudo iptables -F’ and I was disconnected from SSH and can’t access it now…

@Shaun: You can use the Remote Console (<a href=“https://cloud.digitalocean.com/droplets”>https://cloud.digitalocean.com/droplets</a>, select your droplet, and click the Remote Console button at the top-right corner of the page) to regain access to your droplet.

Hi!

Cool stuff! I am trying to set up it, but psad does not show any alert when I run “sudo service psad status” even after the scan “sudo nmap -PN -sS server_domain_or_ip” from an other machine… What that could be?

Thanks!

Alex

(1) replies

Been trying to follow this for a centos 7 Machine. I found the psad RPM so downloaded and installed it. But haven’t found the iptables-persistent RPM. Any ideas, please?

(2) replies

Could the logging of iptables produce a performance issue on high load servers?

(1) replies

You really don’t need to use iptable settings… You can use UFW, https://www.digitalocean.com/community/tutorials/how-to-setup-a-firewall-with-ufw-on-an-ubuntu-and-debian-cloud-server along with the settings from the above article for psad.

I have message from support with content “We have blocked someone from your IP space for abuse. Reason: Port Scanning” How can’t I do to fix my server with problem? I try use uwf to block all port, open only port 80 to fix this problem. But I want to find exactly what programs are running port scans from my server to fix the problem thoroughly.

Hi,

I install psad 2.2.3 on server running RedHat 6.4.
The firewall log the DROP lines and psad send mail about them.

The problems are:

Each time I run service psad restart I get: Shutting down the psad psadwatchd daemon: ** [FAILED]* Shutting down the psad daemon: [ OK ] Starting psad: [ OK ] *

When I run service psad status, to see the current status of psad detected events, I get: psad (pid 11335) is running… psadwatchd is stopped

Why? Thanks.

Hello,

I installed psad on Ubuntu 14.04 and I get this error by email: You may just need to add a default logging rule to the /sbin/iptables 'filter' 'INPUT' chain (…). I think I configured it correctly…

This is the end portion of my iptables:

-A INPUT -p tcp -m tcp --dport 80 -j ACCEPT
-A INPUT -j LOG
-A INPUT -j DROP
-A FORWARD -j LOG

And my complete ip6tables (even if I didn’t enable IPv6 when I created the droplet):

-P INPUT ACCEPT
-P FORWARD ACCEPT
-P OUTPUT ACCEPT
-A INPUT -j LOG
-A INPUT -j DROP
-A FORWARD -j LOG

I see in the psad status that it is logging events. Is there something missing?

Thanks!

I’m not sure but I think the problem comes from Fail2ban, which is adding rules before the other iptables ones.

-P INPUT ACCEPT
-P FORWARD ACCEPT
-P OUTPUT ACCEPT
-N fail2ban-ssh
-N fail2ban-ssh-ddos
-A INPUT -p tcp -m multiport --dports 222 -j fail2ban-ssh-ddos
-A INPUT -p tcp -m multiport --dports 222 -j fail2ban-ssh
-A INPUT -j LOG
-A INPUT -i lo -j ACCEPT
-A INPUT -m conntrack --ctstate RELATED,ESTABLISHED -j ACCEPT
-A INPUT -p tcp -m tcp --dport 222 -j ACCEPT
(…)

Any idea how I can make the LOG rule stay before Fail2ban rules?

(1) replies
Load more comments
This work is licensed under a Creative Commons Attribution-NonCommercial- ShareAlike 4.0 International License.
Deploy on DigitalOcean
Click below to sign up for DigitalOcean's virtual machines, Databases, and AIML products.
Talk to an expert
Connect on Discord
Join the conversation in our Discord to connect with fellow developers
Visit Discord
Featured tutorials
SOLID Design Principles Explained: Building Better Software Architecture
How To Remove Docker Images, Containers, and Volumes
How to Create a MySQL User and Grant Privileges (Step-by-Step)
All tutorials
All topic tags
Become a contributor for community

Get paid to write technical tutorials and select a tech-focused charity to receive a matching donation.

DigitalOcean Documentation

Full documentation for every DigitalOcean product.

Learn more

Resources for startups and AI-native businesses

The Wave has everything you need to know about building a business, from raising funding to marketing your product.

Learn more

Stay up to date, sign up for our newsletter
Email*
Submit
The developer cloud

Scale up as you grow — whether you're running one virtual machine or ten thousand.

View all products
Start building today

From GPU-powered inference and Kubernetes to managed databases and storage, get everything you need to build, scale, and deploy intelligent applications.

Identity and Access Management (IAM)
Write for DOnations
Code of Conduct

Sitemap
This site uses cookies and related technologies, as described in our privacy policy, for purposes that may include site operation, analytics, enhanced user experience, or advertising. You may choose to consent to our use of these technologies, or manage your own preferences. Please visit our cookie policy for more information.



```
sudo apt-get update
sudo apt-get install psad
```


```
sudo apt-get update
sudo apt-get install psad
```


```
sudo iptables -A INPUT -j LOG
sudo iptables -A FORWARD -j LOG
```


```
sudo iptables -A INPUT -j LOG
sudo iptables -A FORWARD -j LOG
```


```
-P INPUT ACCEPT
-P FORWARD ACCEPT
-P OUTPUT ACCEPT
```


```
-P INPUT ACCEPT
-P FORWARD ACCEPT
-P OUTPUT ACCEPT
```


```
sudo iptables -A INPUT -i lo -j ACCEPT
```


```
sudo iptables -A INPUT -i lo -j ACCEPT
```


```
sudo iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
```


```
sudo iptables -A INPUT -m conntrack --ctstate ESTABLISHED,RELATED -j ACCEPT
```


```
sudo iptables -A INPUT -p tcp --dport 22 -j ACCEPT
```


```
sudo iptables -A INPUT -p tcp --dport 22 -j ACCEPT
```


```
sudo iptables -A INPUT -p tcp --dport 80 -j ACCEPT
```


```
sudo iptables -A INPUT -p tcp --dport 80 -j ACCEPT
```


```
sudo iptables -A INPUT -p protocol --dport port_num -j ACCEPT
```


```
sudo iptables -A INPUT -p protocol --dport port_num -j ACCEPT
```


```
sudo iptables -A INPUT -j LOG
```


```
sudo iptables -A INPUT -j LOG
```


```
sudo iptables -A FORWARD -j LOG
```


```
sudo iptables -A FORWARD -j LOG
```


```
sudo iptables -A INPUT -j DROP
```


```
sudo iptables -A INPUT -j DROP
```


```
sudo iptables -P INPUT DROP
```


```
sudo iptables -P INPUT DROP
```


```
sudo iptables -P INPUT ACCEPT
sudo iptables -F
```


```
sudo iptables -P INPUT ACCEPT
sudo iptables -F
```


```
sudo apt-get install iptables-persistent
sudo service iptables-persistent start
```


```
sudo apt-get install iptables-persistent
sudo service iptables-persistent start
```


```
sudo nano /etc/psad/psad.conf
```


```
sudo nano /etc/psad/psad.conf
```


```
EMAIL_ADDRESSES     address1@domain.com, address2@other.com;

HOSTNAME            your_domain.com;
```


```
EMAIL_ADDRESSES     address1@domain.com, address2@other.com;

HOSTNAME            your_domain.com;
```


```
DANGER_LEVEL1           5;
DANGER_LEVEL2           15;
DANGER_LEVEL3           150;
DANGER_LEVEL4           1500;
DANGER_LEVEL5           10000;
```


```
DANGER_LEVEL1           5;
DANGER_LEVEL2           15;
DANGER_LEVEL3           150;
DANGER_LEVEL4           1500;
DANGER_LEVEL5           10000;
```


```
PORT_RANGE_SCAN_THRESHOLD       1;
```


```
PORT_RANGE_SCAN_THRESHOLD       1;
```


- [Prompt Caching is now GA on DigitalOcean Serverless Inference](https://www.digitalocean.com/blog/now-available-prompt-caching)
- [Introducing Agent Droplets](https://www.digitalocean.com/pricing/agent-droplets)
- [Black Friday on Cloudways: Get 80% off for 2 months, plus unlimited free migrations](https://www.cloudways.com/en/pricing.php?id=1227510&utm_source=digitalocean.com&utm_medium=referral&utm_campaign=gen-do-ws-mwb-cwdobfcm26tophat&data1=main_website&data2=gen-do-ws-mwb-cwdobfcm26tophat)
- [Blog](https://www.digitalocean.com/blog)
- [Docs](https://docs.digitalocean.com/products)
- [Careers](https://www.digitalocean.com/careers)
- [Get Support](https://www.digitalocean.com/support)
- [Contact Sales](https://www.digitalocean.com/company/contact/sales?referrer=tophat)
- [DigitalOcean](https://www.digitalocean.com/)
- [Browse all products](https://www.digitalocean.com/products)
- [Managed Agents

Run AI agents in the cloud with governed tool access

New](https://www.digitalocean.com/products/managed-agents)
- [Learning Services

Improve agents and models with evidence

New](https://www.digitalocean.com/products/learning-services)
- [Data Services

Store, retrieve, and surface the context you need](https://www.digitalocean.com/products/data-services)
- [Inference Engine

Run inference at scale with policy-driven routing](https://www.digitalocean.com/products/inference-engine)
- [Model Library

Discover, compare, and evaluate AI models](https://www.digitalocean.com/products/model-library)
- [GPU Droplets

GPU-powered virtual machines to build and run AI apps](https://www.digitalocean.com/products/gpu-droplets)
- [Browse all products](https://www.digitalocean.com/products)
- [See all solutions](https://www.digitalocean.com/solutions)
- [AI HR Knowledge Assistant

Deploy AI tools developed for Human Resources](https://www.digitalocean.com/solutions/ai-hr-knowledge-assistant)
- [AI Training GPU

Accelerate model training with dedicated GPU infrastructure](https://www.digitalocean.com/solutions/ai-training-gpu)
- [AI Recommendation Engine

Build tools to personalize user experiences](https://www.digitalocean.com/solutions/ai-recommendation-engine)
- [Multimodal AI

Run models that process multiple data types](https://www.digitalocean.com/solutions/multimodal-ai)
- [GPU Clusters

GPUs clustered together for large-scale tasks](https://www.digitalocean.com/solutions/gpu-clusters)
- [GPU Inference

Serve models efficiently with optimized GPU compute](https://www.digitalocean.com/solutions/gpu-inference)
- [Blog

The latest product releases and insights from our experts](https://www.digitalocean.com/blog)
- [The Wave

Content to level up your business](https://www.digitalocean.com/resources)
- [Tutorials

Our extensive library of technical articles](https://www.digitalocean.com/community/tutorials)
- [Q&A

Answers to your cloud and coding questions](https://www.digitalocean.com/community/questions)
- [YouTube

Educational content and tutorials](https://youtube.com/DigitalOcean)
- [Visit DigitalOcean's Community Site](https://www.digitalocean.com/community)
- [About Partner Pod

Discounts, revenue share, and more for businesses](https://www.digitalocean.com/partners/pod)
- [AI Partner Program

Boost your AI business](https://www.digitalocean.com/partners/ai-partner-program)
- [DigitalOcean Startups

Resources and support to propel your startup](https://www.digitalocean.com/startups)
- [Partners Directory

Current list of DigitalOcean Partners](https://www.digitalocean.com/partners/directory)
- [Customer Stories

Customers growing on DigitalOcean](https://www.digitalocean.com/customers)
- [Need help? Talk to an expert](https://www.digitalocean.com/company/contact/sales?referrer=mainmenu/partners)
- [Become a Partner](https://www.digitalocean.com/partners/apply)
- [Pricing](https://www.digitalocean.com/pricing)
- [Community](https://www.digitalocean.com/api/dynamic-content/v1/login?success_redirect=https%3A%2F%2Fwww.digitalocean.com%2Fcommunity%2Ftutorials%2Fhow-to-use-psad-to-detect-network-intrusion-attempts-on-an-ubuntu-vps&error_redirect=https%3A%2F%2Fwww.digitalocean.com%2Fauth-error&type=login)
- [DigitalOcean](https://cloud.digitalocean.com/login)
- [Community](https://www.digitalocean.com/api/dynamic-content/v1/login?success_redirect=https%3A%2F%2Fwww.digitalocean.com%2Fcommunity%2Ftutorials%2Fhow-to-use-psad-to-detect-network-intrusion-attempts-on-an-ubuntu-vps&error_redirect=https%3A%2F%2Fwww.digitalocean.com%2Fauth-error&type=register)
- [DigitalOcean](https://cloud.digitalocean.com/registrations/new)
- [Community](https://www.digitalocean.com/api/dynamic-content/v1/login?success_redirect=https%3A%2F%2Fwww.digitalocean.com%2Fcommunity%2Ftutorials%2Fhow-to-use-psad-to-detect-network-intrusion-attempts-on-an-ubuntu-vps&error_redirect=https%3A%2F%2Fwww.digitalocean.com%2Fauth-error&type=login)
- [DigitalOcean](https://cloud.digitalocean.com/login)
- [Community](https://www.digitalocean.com/api/dynamic-content/v1/login?success_redirect=https%3A%2F%2Fwww.digitalocean.com%2Fcommunity%2Ftutorials%2Fhow-to-use-psad-to-detect-network-intrusion-attempts-on-an-ubuntu-vps&error_redirect=https%3A%2F%2Fwww.digitalocean.com%2Fauth-error&type=register)
- [DigitalOcean](https://cloud.digitalocean.com/registrations/new)
- [Tutorials](https://www.digitalocean.com/community/tutorials)
- [Questions](https://www.digitalocean.com/community/questions)
- [Product Docs](https://docs.digitalocean.com/)
- [Tutorials](https://www.digitalocean.com/community/tutorials?subtype=tutorial)
- [Security](https://www.digitalocean.com/community/tags/security)
- [Tutorial](https://www.digitalocean.com/community/tutorials?subtype=tutorial)
- [https://twitter.com/intent/tweet?url=https%3A%2F%2Fwww.digitalocean.com%2Fcommunity%2Ftutorials%2Fhow-to-use-psad-to-det](https://twitter.com/intent/tweet?url=https%3A%2F%2Fwww.digitalocean.com%2Fcommunity%2Ftutorials%2Fhow-to-use-psad-to-detect-network-intrusion-attempts-on-an-ubuntu-vps%3Futm_medium%3Dcommunity%26utm_source%3Dtwshare%26utm_content%3Dhow-to-use-psad-to-detect-network-intrusion-attempts-on-an-ubuntu-vps&text=&via=digitalocean)
- [https://www.facebook.com/sharer/sharer.php?u=https%3A%2F%2Fwww.digitalocean.com%2Fcommunity%2Ftutorials%2Fhow-to-use-psa](https://www.facebook.com/sharer/sharer.php?u=https%3A%2F%2Fwww.digitalocean.com%2Fcommunity%2Ftutorials%2Fhow-to-use-psad-to-detect-network-intrusion-attempts-on-an-ubuntu-vps%3Futm_medium%3Dcommunity%26utm_source%3Dtwshare%26utm_content%3Dhow-to-use-psad-to-detect-network-intrusion-attempts-on-an-ubuntu-vps&t=)
- [https://www.linkedin.com/shareArticle?mini=true&url=https%3A%2F%2Fwww.digitalocean.com%2Fcommunity%2Ftutorials%2Fhow-to-](https://www.linkedin.com/shareArticle?mini=true&url=https%3A%2F%2Fwww.digitalocean.com%2Fcommunity%2Ftutorials%2Fhow-to-use-psad-to-detect-network-intrusion-attempts-on-an-ubuntu-vps%3Futm_medium%3Dcommunity%26utm_source%3Dtwshare%26utm_content%3Dhow-to-use-psad-to-detect-network-intrusion-attempts-on-an-ubuntu-vps&title=)
- [https://news.ycombinator.com/submitlink?u=https%3A%2F%2Fwww.digitalocean.com%2Fcommunity%2Ftutorials%2Fhow-to-use-psad-t](https://news.ycombinator.com/submitlink?u=https%3A%2F%2Fwww.digitalocean.com%2Fcommunity%2Ftutorials%2Fhow-to-use-psad-to-detect-network-intrusion-attempts-on-an-ubuntu-vps%3Futm_medium%3Dcommunity%26utm_source%3Dtwshare%26utm_content%3Dhow-to-use-psad-to-detect-network-intrusion-attempts-on-an-ubuntu-vps&t=)
- [Security](https://www.digitalocean.com/community/tags/security)
- [Ubuntu](https://www.digitalocean.com/community/tags/ubuntu)
- [Firewall](https://www.digitalocean.com/community/tags/firewall)
- [Monitoring](https://www.digitalocean.com/community/tags/monitoring)
- [Justin Ellingwood](https://www.digitalocean.com/community/users/jellingwood)
- [Install psad](https://www.digitalocean.com/community/tutorials/how-to-use-psad-to-detect-network-intrusion-attempts-on-an-ubuntu-vps#install-psad)
- [Configure IPTables Rules](https://www.digitalocean.com/community/tutorials/how-to-use-psad-to-detect-network-intrusion-attempts-on-an-ubuntu-vps#configure-iptables-rules)
- [Configure psad to Detect Scans](https://www.digitalocean.com/community/tutorials/how-to-use-psad-to-detect-network-intrusion-attempts-on-an-ubuntu-vps#configure-psad-to-detect-scans)
- [Implement psad Intrusion Detection](https://www.digitalocean.com/community/tutorials/how-to-use-psad-to-detect-network-intrusion-attempts-on-an-ubuntu-vps#implement-psad-intrusion-detection)
- [Perform a Test Port Scan](https://www.digitalocean.com/community/tutorials/how-to-use-psad-to-detect-network-intrusion-attempts-on-an-ubuntu-vps#perform-a-test-port-scan)
- [Implement Intrusion Prevention](https://www.digitalocean.com/community/tutorials/how-to-use-psad-to-detect-network-intrusion-attempts-on-an-ubuntu-vps#implement-intrusion-prevention)
- [Conclusion](https://www.digitalocean.com/community/tutorials/how-to-use-psad-to-detect-network-intrusion-attempts-on-an-ubuntu-vps#conclusion)
- [https://www.digitalocean.com/community/tutorials/how-to-use-psad-to-detect-network-intrusion-attempts-on-an-ubuntu-vps#i](https://www.digitalocean.com/community/tutorials/how-to-use-psad-to-detect-network-intrusion-attempts-on-an-ubuntu-vps#introduction)
- [https://www.digitalocean.com/community/tutorials/how-to-use-psad-to-detect-network-intrusion-attempts-on-an-ubuntu-vps#i](https://www.digitalocean.com/community/tutorials/how-to-use-psad-to-detect-network-intrusion-attempts-on-an-ubuntu-vps#install-psad)
- [https://www.digitalocean.com/community/tutorials/how-to-use-psad-to-detect-network-intrusion-attempts-on-an-ubuntu-vps#c](https://www.digitalocean.com/community/tutorials/how-to-use-psad-to-detect-network-intrusion-attempts-on-an-ubuntu-vps#configure-iptables-rules)
- [https://www.digitalocean.com/community/tutorials/how-to-use-psad-to-detect-network-intrusion-attempts-on-an-ubuntu-vps#c](https://www.digitalocean.com/community/tutorials/how-to-use-psad-to-detect-network-intrusion-attempts-on-an-ubuntu-vps#configure-psad-to-detect-scans)
- [port knocking](https://www.digitalocean.com/community/tutorials/how-to-use-port-knocking-to-hide-your-ssh-daemon-from-attackers-on-ubuntu)
- [https://www.digitalocean.com/community/tutorials/how-to-use-psad-to-detect-network-intrusion-attempts-on-an-ubuntu-vps#i](https://www.digitalocean.com/community/tutorials/how-to-use-psad-to-detect-network-intrusion-attempts-on-an-ubuntu-vps#implement-psad-intrusion-detection)
- [https://www.digitalocean.com/community/tutorials/how-to-use-psad-to-detect-network-intrusion-attempts-on-an-ubuntu-vps#p](https://www.digitalocean.com/community/tutorials/how-to-use-psad-to-detect-network-intrusion-attempts-on-an-ubuntu-vps#perform-a-test-port-scan)
- [https://www.digitalocean.com/community/tutorials/how-to-use-psad-to-detect-network-intrusion-attempts-on-an-ubuntu-vps#i](https://www.digitalocean.com/community/tutorials/how-to-use-psad-to-detect-network-intrusion-attempts-on-an-ubuntu-vps#implement-intrusion-prevention)
- [https://www.digitalocean.com/community/tutorials/how-to-use-psad-to-detect-network-intrusion-attempts-on-an-ubuntu-vps#t](https://www.digitalocean.com/community/tutorials/how-to-use-psad-to-detect-network-intrusion-attempts-on-an-ubuntu-vps#test-intrusion-prevention)
- [https://www.digitalocean.com/community/tutorials/how-to-use-psad-to-detect-network-intrusion-attempts-on-an-ubuntu-vps#c](https://www.digitalocean.com/community/tutorials/how-to-use-psad-to-detect-network-intrusion-attempts-on-an-ubuntu-vps#conclusion)
- [tripwire](https://www.digitalocean.com/community/tutorials/how-to-use-tripwire-to-detect-server-intrusions-on-an-ubuntu-vps)
- [Learn more about our products](https://www.digitalocean.com/products)

## 3. Comparative Data & Specs
| Name | Name | Last commit message | Last commit date |
| --- | --- | --- | --- |
| deps | deps | add reputation feed https://rules.emergingthreats.net/blockrules/comp… |  |
| doc | doc | moved to doc directory |  |
| images | images | start on markdown format for README |  |
| init-scripts | init-scripts | update systemd init script from github user @rathann |  |
| misc | misc | use new-> |  |
| packaging | packaging | bump version to 2.4.6 |  |
| patches | patches | updated iptables trailing space link |  |
| selinux | selinux | (Miroslav Grepl) Contributed policy file to make psad compatible with… |  |
| test | test | add reputation_scan |  |
| CREDITS | CREDITS | minor spacing fixes |  |
| ChangeLog | ChangeLog | more reputation feed work to enable it within scan data structures |  |
| LICENSE | LICENSE | minor spacing fixes |  |
| Makefile | Makefile | minor spacing fixes |  |
| README | README | add README link |  |
| README.md | README.md | minor spacing fixes |  |
| VERSION | VERSION | start on test suite support for reputation feed tests |  |
| auto_dl | auto_dl | minor spacing fixes |  |
| fwcheck_psad.pl | fwcheck_psad.pl | implement IP network reputation feed detection (in addition to just s… |  |
| icmp6_types | icmp6_types | minor spacing fixes |  |
| icmp_types | icmp_types | minor spacing fixes |  |
| install.answers.example | install.answers.example | Added install.answers.example file to illustrate install.pl answers t… |  |
| install.pl | install.pl | add IP_INFO data to email alerts, defaults to Talos |  |
| ip_options | ip_options | start on test suite support for reputation feed tests |  |
| kmsgsd.c | kmsgsd.c | minor spacing fixes |  |
| nf2csv | nf2csv | minor spacing fixes |  |
| pf.os | pf.os | minor spacing fixes |  |
| posf | posf | Removed "$Id$" tags (meaningless for git) |  |
| protocols | protocols | added 'protocols' file in support of IP protocol scan detection (nmap… |  |
| psad | psad | add IP_INFO data to email alerts, defaults to Talos |  |
| psad.conf | psad.conf | fix for missing semicolon for IP_INFO variable, fixes #59 |  |
| psad.h | psad.h | start on test suite support for reputation feed tests |  |
| psad_funcs.c | psad_funcs.c | start on test suite support for reputation feed tests |  |
| psadwatchd.c | psadwatchd.c | Bugfix: String pointer not dereferenced. |  |
| signatures | signatures | interim work to replace all 'arachnids' references with valid updated… |  |
| snort_rule_dl | snort_rule_dl | Removed "$Id$" tags (meaningless for git) |  |
| strlcat.c | strlcat.c | minor spacing fixes |  |
| strlcpy.c | strlcpy.c | minor spacing fixes |  |
| View all files |  |  |  |



|  |
| --- |

## 4. Complete Actionable Steps / Execution Guide
DATA NOT CAPTURED: no procedure-shaped steps were present in the captured sources. Steps are never fabricated from unrelated prose.

## Research limitations
The two-stage relevance gate (deterministic pre-filter + deterministic relevance judge) removed or quarantined the following pages; they do NOT contribute any prose, facts, tables, citations, or images to this guide.

- **reject**: https://github.com/ (homepage (no article signal))
- **deprioritized**: https://linuxsecurity.com/features/meet-the-anti-nmap-psad (page cap 3 reached)
- **deprioritized**: https://www.cipherdyne.com/psad/ (page cap 3 reached)
- **deprioritized**: http://cipherdyne.org/psad/ (page cap 3 reached)
- **deprioritized**: https://www.cipherdyne.org/LinuxFirewalls/ch07/ (page cap 3 reached)

---

## 5. Primary Sources & Media Links
- [GitHub - mrash/psad: psad: Intrusion Detection and Log Analysis with iptables · GitHub (relevance 100)](https://github.com/mrash/psad)
- [psad - Intrusion Detection with iptables, iptables Log Analysis, iptables Policy Analysis (relevance 100)](https://www.cipherdyne.org/psad/)
- [How To Use psad to Detect Network Intrusion Attempts on an Ubuntu VPS | DigitalOcean (relevance 93)](https://www.digitalocean.com/community/tutorials/how-to-use-psad-to-detect-network-intrusion-attempts-on-an-ubuntu-vps)
