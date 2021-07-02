#!/usr/bin/env python3
import asyncio
import contextlib
from collections import defaultdict
import re
from typing import *


SERVERS = {
	'cloudflare': ['1.1.1.1', '1.0.0.1'],
	'google': ['8.8.8.8', '8.8.4.4'],
}

# most visited websites in the US May 2021
DOMAINS = [
	'google.com',
	'youtube.com',
	'facebook.com',
	'amazon.com',
	'wikipedia.org',
	'yahoo.com',
	'reddit.com',
	'pornhub.com',
	'instagram.com',
	'twitter.com',
	'ebay.com',
	'xvideos.com',
	'fandom.com',
	'cnn.com',
	'craigslist.org',
	'walmart.com',
	'weather.com',
	'xnxx.com',
	'espn.com',
	'imdb.com',
	'zoom.us',
	'foxnews.com',
	'linkedin.com',
	'bing.com',
	'microsoft.com',
	'live.com',
	'usps.com',
	'msn.com',
	'homedepot.com',
	'paypal.com',
	'xhamster.com',
	'indeed.com',
	'duckduckgo.com',
	'etsy.com',
	'zillow.com',
	'pinterest.com',
	'office.com',
	'nytimes.com',
	'twitch.tv',
	'quora.com',
	'accuweather.com',
	'apple.com',
	'netflix.com',
	'healthline.com',
	'target.com',
	'instructure.com',
	'bestbuy.com',
	'yelp.com',
	'att.com',
	'lowes.com',
	'ups.com',
	't-mobile.com',
	'microsoftonline.com',
	'fedex.com',
	'washingtonpost.com',
	'realtor.com',
	'chase.com',
	'quizlet.com',
	'webmd.com',
	'github.com',
	'stackoverflow.com',
	'archiveofourown.org',
	'bbc.com',
	'wellsfargo.com',
	'xfinity.com',
	'aol.com',
	'chaturbate.com',
	'intuit.com',
	'tripadvisor.com',
	'cheatsheet.com',
	'nih.gov',
	'bankofamerica.com',
	'adobe.com',
	'wayfair.com',
	'weather.gov',
	'usatoday.com',
	'ca.gov',
	'cnbc.com',
	'allrecipes.com',
	'capitalone.com',
	'dailymail.co.uk',
	'samsung.com',
	'drudgereport.com',
	'hulu.com',
	'businessinsider.com',
	'roblox.com',
	'spankbang.com',
	'npr.org',
	'fidelity.com',
	'nypost.com',
	'pch.com',
	'onlyfans.com',
	'adp.com',
	'imgur.com',
	'mayoclinic.org',
	'costco.com',
	'youporn.com',
	'theguardian.com',
	'marketwatch.com',
	'ign.com',
]


class PingResults:
	INT = r'\d+'
	FLOAT = r'\d+\.?\d*'
	PING_RESULTS_REGEX = re.compile(
		fr'(?P<transmitted>{INT}) packets transmitted, (?P<received>{INT}) received, (?:\+{INT} errors, )?(?P<packet_loss>{FLOAT})% packet loss, time {FLOAT}ms\n'
		fr'(?:rtt min/avg/max/mdev = (?P<min>{FLOAT})/(?P<avg>{FLOAT})/(?P<max>{FLOAT})/(?P<mdev>{FLOAT}) ms)?\n'
		fr'\Z',
		re.MULTILINE,
	)

	def __init__(self, output):
		m = self.PING_RESULTS_REGEX.search(output)
		if not m:
			raise RuntimeError('\n' + output)
		self.transmitted = int(m.group('transmitted'))
		self.received = int(m.group('received'))
		self.packet_loss = float(m.group('packet_loss')) / 100
		self.min = self._float_or_none(m.group('min'))
		self.avg = self._float_or_none(m.group('avg'))
		self.max = self._float_or_none(m.group('max'))
		self.mdev = self._float_or_none(m.group('mdev'))

	@staticmethod
	def _float_or_none(f):
		return None if f is None else float(f)

	def __repr__(self):
		return str(self.__dict__)

async def ping(addr, count=1) -> PingResults:
	proc = await asyncio.create_subprocess_exec(
		'ping', '-qc1', addr,
		stdout=asyncio.subprocess.PIPE,
		stderr=asyncio.subprocess.PIPE,
	)
	stdout, stderr = await proc.communicate()
	try:
		return PingResults(stdout.decode())
	except Exception as e:
		raise RuntimeError(stderr.decode()) from e


async def dig(domain, server=None) -> Optional[str]:
	cmd = ['dig', '+short']
	if server is not None:
		cmd.append(f'@{server}')
	cmd.append(domain)
	proc = await asyncio.create_subprocess_exec(
		*cmd,
		stdout=asyncio.subprocess.PIPE,
		stderr=asyncio.subprocess.PIPE,
	)
	stdout, stderr = await proc.communicate()
	if proc.returncode:
		raise RuntimeError(stderr.decode())
	addrs = stdout.decode().strip().split()
	if not addrs:
		return None
	return addrs[0]

async def get_results(domain, server=None, provider=None, count=1, semaphore=None) -> Optional[PingResults]:
	if semaphore is None:
		semaphore = contextlib.AsyncExitStack()
	async with semaphore:
		try:
			addr = await dig(domain, server=server)
		except asyncio.CancelledError:
			raise
		except Exception as e:
			raise RuntimeError(f'Dig error: {domain} from {provider} ({server})') from e
		if addr is None:
			return None
		try:
			results = await ping(addr, count=count)
		except asyncio.CancelledError:
			raise
		except Exception as e:
			raise RuntimeError(f'Ping error: {domain} ({addr}) from {provider} ({server})') from e
		return results


async def main():
	num_domains = 100 # between 1 and 100
	best_of = 3
	semaphore = asyncio.Semaphore(50)

	# alternate between IPs for the same provider
	server_addrs = []
	for server, addrs in SERVERS.items():
		for i, addr in enumerate(addrs):
			if len(server_addrs) <= i:
				server_addrs.append([])
			server_addrs[i].append((server, addr))
	server_addrs = [server_item for server_list in server_addrs for server_item in server_list]
	# print('DNS Servers:', server_addrs)

	providers = []
	domains = []
	awaitables = []
	for domain in DOMAINS[:num_domains]:
		for provider, server in server_addrs:
			providers.append(provider)
			domains.append(domain)
			awaitables.append(get_results(domain, server=server, provider=provider, count=best_of, semaphore=semaphore))
	results = await asyncio.gather(*awaitables)

	mins = [None if result is None else result.min for result in results]
	# print(f'Best of {best_of} (msec):', list(zip(providers, domains, mins)))

	results_by_provider = defaultdict(lambda: defaultdict(list)) # domain -> provider -> mins
	for provider, domain, _min in zip(providers, domains, mins):
		results_by_provider[domain][provider].append(_min)
	for d in results_by_provider.values():
		for key, mins in d.items():
			filtered = list(filter(None, mins))
			_sum = sum(filtered)
			filtered_len = len(filtered)
			d[key] = (str(_sum / filtered_len) if filtered_len else '∞') + ('' if filtered_len == len(mins) else f' ({filtered_len}/{len(mins)})')

	# print table
	print('\t' + '\t'.join(SERVERS.keys()))
	for domain, d in results_by_provider.items():
		print('\t'.join((domain, *(str(d[provider]) for provider in SERVERS))))

if __name__ == '__main__':
	asyncio.run(main())
