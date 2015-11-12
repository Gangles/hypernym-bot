#!/usr/bin/python
# -*- coding: utf-8 -*-

import blacklist
import config
import datetime
import logging
import random
import requests
import sys
import time
from twython import Twython
from wordnik import *

def getRandomWords(wordnik):
    # get a list of random words from the wordnik API
    random = WordsApi.WordsApi(wordnik).getRandomWords(
    	includePartOfSpeech='noun',
    	minCorpusCount=1000,
        minDictionaryCount=10,
        hasDictionaryDef='true',
        maxLength=10)
    
    assert random and len(random) > 0, "Wordnik API error"
    
    # filter out offensive words
    wordList=[]
    for r in random:
        if not blacklist.isOffensive(r.word):
            wordList.append(r.word)
    
    return wordList

def isNoun(wordnik, word):
	# check if the given word is a noun
	results = WordApi.WordApi(wordnik).getDefinitions(
		word=word, limit=1, useCanonical=True)
	if not results:
		return False
	for r in results:
		if r.partOfSpeech == 'noun':
			return True
	return False

def isUncountable(word):
	# can we precede this word with 'a' or not?
	url = 'https://en.wiktionary.org/w/api.php'
	query = {'action':'query', 'format':'json',
			'prop':'categories', 'titles':word}
	r = requests.get(url, params=query)
	if not r: return False # assume countable
	if 'English uncountable nouns' in str(r.json()):
		return True # words that are uncountable
	if 'English pluralia tantum' in str(r.json()):
		return True # words that are always plural
	return False

def getHypernyms(wordnik, word):
	# get hypernyms for the given word
	query = WordApi.WordApi(wordnik).getRelatedWords(
		word = word, relationshipTypes = 'hypernym')
	hypernyms = []
	if not query:
		return hypernyms
	for q in query:
		for hyp in q.words:
			if hyp not in word and not blacklist.isOffensive(hyp):
				if isNoun(wordnik, hyp):
					hypernyms.append(hyp)
	return hypernyms

def connect_twitter():
    # connect to twitter API
    return Twython(config.twitter_key, config.twitter_secret,
    			config.access_token, config.access_secret)

def postTweet(twitter, to_tweet):
    # post the given tweet
    print "Posting tweet: " + to_tweet.encode('ascii', 'ignore')
    twitter.update_status(status=to_tweet)

def getArticle(word, approx=False):
	# preceded by 'a' or 'an'?
	if not approx and isUncountable(word):
		return ''
	elif word[0] in 'aeiou':
		return 'an '
	else:
		return 'a '

def tweetLength(first, second, third, fourth=None):
	length = 95 if fourth else 63 # length of boilerplate
	length += len(getArticle(first, True)) + len(first)
	length += len(getArticle(second, True)) + len(second) * 2
	length += len(third)
	if fourth:
		length += len(getArticle(third, True)) + len(third)
		length += len(fourth)
	return length

def assembleTweet():
	wordnik = swagger.ApiClient(config.wordnik_key, 'http://api.wordnik.com/v4')
	firstList = getRandomWords(wordnik)
	first, second, third, fourth = (None, None, None, None)

	while not first and len(firstList) > 0:
		# choose a random first word, find its hypernyms
		first = firstList.pop()
		secondList = getHypernyms(wordnik, first)
		random.shuffle(secondList)
		while not second and len(secondList) > 0:
			# choose a second word, find its hypernyms
			second = secondList.pop()
			thirdList = getHypernyms(wordnik, second)
			random.shuffle(thirdList)
			while not third and len(thirdList) > 0:
				# choose a third word...
				third = thirdList.pop()
				# is our sentence already too long?
				if tweetLength(first, second, third) > 140:
					third = None
					continue
				# try to find a fourth word that will fit
				fourthList = getHypernyms(wordnik, third)
				random.shuffle(fourthList)
				while not fourth and len(fourthList) > 0:
					fourth = fourthList.pop()
					if tweetLength(first, second, third, fourth) > 140:
						fourth = None
				# if our 3-word sentence is long, good enough
				if tweetLength(first, second, third) > 95:
					break
				if not fourth:
					third = None
			if not third:
				second = None
		if not second:
			first = None
	assert first and second and third, "Unable to assemble a tweet"

	toTweet = "For the want of %s%s, the %s was lost" % (getArticle(first), first, second)
	toTweet += "\nFor the want of %s%s, the %s was lost" % (getArticle(second), second, third)
	if fourth:
		toTweet += "\nFor the want of %s%s, the %s was lost" % (getArticle(third), third, fourth)
	return toTweet

def timeToWait():
    # tweet every 4 hours, offset by 2 hours
    now = datetime.datetime.now()
    wait = 60 - now.second
    wait += (59 - now.minute) * 60
    wait += (3 - ((now.hour + 2) % 4)) * 3600
    return wait

if __name__ == "__main__":
	# heroku scheduler runs every 10 minutes
	wait = timeToWait()
	print "Wait " + str(wait) + " seconds for next tweet"
	if wait < 5 or wait > 595: sys.exit(0)
	
	try:
		tweet = assembleTweet()
		time.sleep(wait)
		twitter = connect_twitter()
		postTweet(twitter, tweet)
		sys.exit(0)
	except SystemExit as e:
		# working as intended, exit normally
		sys.exit(e)
	except:
		# actual error, don't try again
		logging.exception(sys.exc_info()[0])
		sys.exit(1) # error
